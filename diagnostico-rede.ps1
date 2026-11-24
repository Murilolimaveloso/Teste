<#
  diagnostico-rede.ps1
  Diagnostico de lentidao de rede / roteador para Windows 10 e 11.

  SOMENTE LEITURA: o script nao altera nenhuma configuracao do PC nem do roteador.

  Como rodar (no PowerShell, na pasta onde salvou o arquivo):
      powershell -ExecutionPolicy Bypass -File .\diagnostico-rede.ps1

  Opcao:  -Rapido   pula a varredura de aparelhos, o tracert e o teste de velocidade.

  Leva de 3 a 5 minutos. O relatorio e salvo na Area de Trabalho como
  diagnostico-rede-AAAAMMDD-HHMM.txt
#>
[CmdletBinding()]
param([switch]$Rapido)

$ErrorActionPreference = 'Continue'
$ProgressPreference    = 'SilentlyContinue'

$stamp   = Get-Date -Format 'yyyyMMdd-HHmm'
$desktop = [Environment]::GetFolderPath('Desktop')
if (-not $desktop -or -not (Test-Path $desktop)) { $desktop = $env:USERPROFILE }
$OutFile = Join-Path $desktop "diagnostico-rede-$stamp.txt"
$Alertas = New-Object System.Collections.Generic.List[string]

# ---------------------------------------------------------------- utilitarios
function Log {
    param([string]$Text = '')
    Write-Host $Text
    Add-Content -Path $OutFile -Value $Text -Encoding UTF8
}
function Secao {
    param([string]$Titulo)
    Log ''
    Log ('=' * 72)
    Log "  $Titulo"
    Log ('=' * 72)
}
function LogObj {
    param($Obj)
    if ($null -eq $Obj) { return }
    $s = ($Obj | Out-String -Width 220).TrimEnd()
    if ($s) { Log $s }
}
function Alerta {
    param([string]$Msg)
    $Alertas.Add($Msg)
    Write-Host "  [!] $Msg" -ForegroundColor Yellow
    Add-Content -Path $OutFile -Value "  [!] $Msg" -Encoding UTF8
}

function Testar-Ping {
    param([string]$Alvo, [int]$Qtd = 50, [int]$Timeout = 1000)
    $p      = New-Object System.Net.NetworkInformation.Ping
    $tempos = New-Object System.Collections.Generic.List[double]
    $perdas = 0
    for ($i = 0; $i -lt $Qtd; $i++) {
        try {
            $r = $p.Send($Alvo, $Timeout)
            if ($r.Status -eq 'Success') { $tempos.Add([double]$r.RoundtripTime) } else { $perdas++ }
        } catch { $perdas++ }
        Start-Sleep -Milliseconds 100
    }
    $res = [ordered]@{
        Alvo = $Alvo; Enviados = $Qtd; Perdidos = $perdas
        'Perda%' = [math]::Round(100 * $perdas / $Qtd, 1)
        'Min ms' = $null; 'Media ms' = $null; 'Max ms' = $null; 'Jitter ms' = $null
    }
    if ($tempos.Count -gt 0) {
        $m = $tempos | Measure-Object -Minimum -Maximum -Average
        $res['Min ms']   = $m.Minimum
        $res['Max ms']   = $m.Maximum
        $res['Media ms'] = [math]::Round($m.Average, 1)
        $j = 0.0
        if ($tempos.Count -gt 1) {
            for ($i = 1; $i -lt $tempos.Count; $i++) { $j += [math]::Abs($tempos[$i] - $tempos[$i - 1]) }
            $j = $j / ($tempos.Count - 1)
        }
        $res['Jitter ms'] = [math]::Round($j, 1)
    }
    [pscustomobject]$res
}

Set-Content -Path $OutFile -Value "Diagnostico de rede - $(Get-Date)" -Encoding UTF8
Log "Computador: $env:COMPUTERNAME   Windows: $([Environment]::OSVersion.VersionString)"
Write-Host "Relatorio sendo salvo em: $OutFile" -ForegroundColor Cyan

# ---------------------------------------------------------------- 1. adaptador e roteador
Secao '1. Adaptadores de rede e roteador (gateway)'

$cfg = Get-NetIPConfiguration -ErrorAction SilentlyContinue |
       Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' }
if (-not $cfg) {
    Log 'Nenhum adaptador conectado com gateway foi encontrado. O PC esta conectado na rede?'
    Log "Relatorio: $OutFile"
    return
}
if (@($cfg).Count -gt 1) {
    Log 'Mais de um adaptador com rota para a internet (ex.: VPN + Wi-Fi):'
    LogObj ($cfg | Select-Object InterfaceAlias, @{n='IP';e={$_.IPv4Address.IPAddress}}, @{n='Gateway';e={$_.IPv4DefaultGateway.NextHop}})
}
$cfg       = @($cfg)[0]
$ifIndex   = $cfg.InterfaceIndex
$ifAlias   = $cfg.InterfaceAlias
$ipLocal   = @($cfg.IPv4Address)[0].IPAddress
$gateway   = @($cfg.IPv4DefaultGateway)[0].NextHop
$adaptador = Get-NetAdapter -InterfaceIndex $ifIndex
$ehWifi    = ($adaptador.PhysicalMediaType -match '802\.11') -or ($adaptador.InterfaceDescription -match 'Wi-?Fi|Wireless|WLAN|802\.11')

Log "Adaptador em uso : $ifAlias ($($adaptador.InterfaceDescription))"
Log "Tipo             : $(if ($ehWifi) {'Wi-Fi'} else {'Cabo / outro'})"
Log "Velocidade link  : $($adaptador.LinkSpeed)"
Log "IP deste PC      : $ipLocal"
Log "Roteador         : $gateway"

if (-not $ehWifi -and $adaptador.LinkSpeed -match '^(10|100) Mbps') {
    Alerta "Cabo conectado a apenas $($adaptador.LinkSpeed). Se seu plano e maior que isso, troque o cabo (use Cat5e/Cat6) ou a porta."
}

$vpn = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
    $_.Status -eq 'Up' -and $_.InterfaceDescription -match 'VPN|TAP-|WireGuard|Wintun|Tunnel|OpenVPN|Fortinet|Cisco AnyConnect|ZeroTier|Tailscale|Hamachi'
}
if ($vpn) {
    Alerta "VPN/tunel ativo: $(($vpn | ForEach-Object Name) -join ', '). VPN costuma deixar a conexao mais lenta."
}

Log ''
Log 'Todos os adaptadores ativos:'
LogObj (Get-NetAdapter | Where-Object Status -eq 'Up' | Select-Object Name, InterfaceDescription, LinkSpeed, MacAddress)

# ---------------------------------------------------------------- 2. Wi-Fi
$wifiCanal = $null
if ($ehWifi) {
    Secao '2. Sinal Wi-Fi'
    $wi = (netsh wlan show interfaces) | Out-String
    LogObj $wi

    $sinal = $null; $rx = $null
    if ($wi -match '(?m)^\s*(Signal|Sinal)\s*:\s*(\d+)\s*%')            { $sinal = [int]$Matches[2] }
    if ($wi -match '(?m)^\s*(Channel|Canal)\s*:\s*(\d+)')               { $wifiCanal = [int]$Matches[2] }
    if ($wi -match '(?m)^\s*(Receive rate|Taxa de rece\S*o)[^:]*:\s*([\d\.,]+)') { $rx = [double]($Matches[2] -replace ',', '.') }

    if ($null -ne $sinal) {
        if ($sinal -lt 50)     { Alerta "Sinal Wi-Fi fraco ($sinal%). Aproxime o PC do roteador, tire o roteador de dentro de armarios/de tras da TV, ou use repetidor/mesh." }
        elseif ($sinal -lt 70) { Alerta "Sinal Wi-Fi apenas razoavel ($sinal%)." }
    }
    if ($null -ne $rx -and $rx -lt 50) {
        Alerta "Taxa de conexao Wi-Fi baixa ($rx Mbps). O Wi-Fi deste PC esta limitando a velocidade."
    }
    if ($null -ne $wifiCanal -and $wifiCanal -le 14) {
        Alerta "Voce esta em 2.4 GHz (canal $wifiCanal). Se o roteador tiver rede 5 GHz, conecte nela: e bem mais rapida e sofre menos interferencia."
        if ($wifiCanal -notin 1, 6, 11) {
            Alerta "Canal $wifiCanal de 2.4 GHz se sobrepoe a outros. Prefira 1, 6 ou 11 nas configuracoes do roteador."
        }
    }

    # Redes vizinhas
    Log ''
    Log 'Redes Wi-Fi vizinhas (para medir interferencia):'
    $nets = (netsh wlan show networks mode=bssid) 2>&1
    $lista = New-Object System.Collections.Generic.List[object]
    $ssidAtual = ''; $item = $null
    foreach ($linha in $nets) {
        $l = [string]$linha
        if ($l -match '^\s*SSID\s+\d+\s*:\s*(.*)$')              { $ssidAtual = $Matches[1].Trim(); continue }
        if ($l -match '^\s*BSSID\s+\d+')                         { $item = [pscustomobject]@{ SSID = $ssidAtual; Sinal = $null; Canal = $null }; $lista.Add($item); continue }
        if ($item -and $l -match '^\s*(Signal|Sinal)\s*:\s*(\d+)\s*%') { $item.Sinal = [int]$Matches[2]; continue }
        if ($item -and $l -match '^\s*(Channel|Canal)\s*:\s*(\d+)')    { $item.Canal = [int]$Matches[2]; continue }
    }
    $lista = @($lista | Where-Object { $null -ne $_.Canal })
    if ($lista.Count -eq 0) {
        Log '  Nao foi possivel listar redes vizinhas. No Windows 11, ative Configuracoes > Privacidade > Localizacao'
        Log '  (o Windows exige isso para escanear Wi-Fi) e rode o script de novo.'
        LogObj ($nets | Select-Object -First 5)
    } else {
        LogObj ($lista | Sort-Object Canal, @{e='Sinal';Descending=$true} | Format-Table -AutoSize)
        Log 'Quantidade de redes por canal:'
        LogObj ($lista | Group-Object Canal | Sort-Object { [int]$_.Name } | Select-Object @{n='Canal';e={$_.Name}}, @{n='Redes';e={$_.Count}} | Format-Table -AutoSize)

        if ($null -ne $wifiCanal) {
            if ($wifiCanal -le 14) {
                $conc = @($lista | Where-Object { $_.Canal -le 14 -and [math]::Abs($_.Canal - $wifiCanal) -lt 5 -and $_.Sinal -ge 30 })
            } else {
                $conc = @($lista | Where-Object { $_.Canal -eq $wifiCanal -and $_.Sinal -ge 30 })
            }
            $conc = [math]::Max(0, $conc.Count - 1)   # desconta a propria rede
            Log "Redes com sinal relevante disputando o seu canal ($wifiCanal): $conc"
            if ($conc -ge 4) {
                $livres24 = 1, 6, 11 | Sort-Object { $c = $_; @($lista | Where-Object { $_.Canal -eq $c }).Count } | Select-Object -First 1
                Alerta "Canal $wifiCanal congestionado ($conc redes vizinhas). Troque o canal no roteador (em 2.4 GHz o menos ocupado agora e o $livres24)."
            }
        }
    }
} else {
    Secao '2. Sinal Wi-Fi'
    Log 'PC conectado por cabo: teste de Wi-Fi pulado. (Para avaliar o Wi-Fi, rode de novo conectado no Wi-Fi.)'
}

# ---------------------------------------------------------------- 3. latencia
Secao '3. Latencia e perda de pacotes (50 pings cada)'
Log 'Testando... (cerca de 30 segundos)'
$pGw  = Testar-Ping -Alvo $gateway
$pCf  = Testar-Ping -Alvo '1.1.1.1'
$pGg  = Testar-Ping -Alvo '8.8.8.8'
LogObj ($pGw, $pCf, $pGg | Format-Table -AutoSize)

$limGwMedia = if ($ehWifi) { 15 } else { 3 }
$gwRuim = $false
if ($pGw.Perdidos -eq $pGw.Enviados) {
    Log 'O roteador nao responde a ping (alguns modelos bloqueiam). Teste do roteador inconclusivo.'
} else {
    if ($pGw.'Perda%' -gt 0)               { $gwRuim = $true; Alerta "Perda de $($pGw.'Perda%')% ate o ROTEADOR. Problema no Wi-Fi/cabo ou roteador sobrecarregado." }
    if ($pGw.'Media ms' -gt $limGwMedia)   { $gwRuim = $true; Alerta "Latencia ate o roteador alta ($($pGw.'Media ms') ms; o normal e < $limGwMedia ms). Interferencia, sinal fraco ou roteador travando." }
    if ($pGw.'Jitter ms' -gt 10)           { $gwRuim = $true; Alerta "Latencia ate o roteador instavel (jitter $($pGw.'Jitter ms') ms)." }
}
$net = if ($pCf.'Perda%' -le $pGg.'Perda%') { $pCf } else { $pGg }
$netRuim = $false
if ($net.'Perda%' -gt 1)     { $netRuim = $true; Alerta "Perda de $($net.'Perda%')% ate a internet." }
if ($net.'Media ms' -gt 80)  { $netRuim = $true; Alerta "Latencia ate a internet alta ($($net.'Media ms') ms)." }
if ($net.'Jitter ms' -gt 20) { $netRuim = $true; Alerta "Latencia ate a internet instavel (jitter $($net.'Jitter ms') ms). Ruim para jogos e chamadas de video." }
if ($netRuim -and -not $gwRuim -and $pGw.Perdidos -lt $pGw.Enviados) {
    Alerta 'A rede local esta boa, mas a internet esta ruim: o problema parece estar na OPERADORA ou no modem. Vale ligar para o suporte com este relatorio.'
}

# ---------------------------------------------------------------- 4. DNS
Secao '4. DNS (tempo para resolver nomes de sites)'
$dnsAtual = @((Get-DnsClientServerAddress -InterfaceIndex $ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue).ServerAddresses)
Log "DNS configurado: $($dnsAtual -join ', ')"
$dominios = 'google.com', 'youtube.com', 'netflix.com', 'wikipedia.org', 'globo.com', 'whatsapp.net'
$servidores = @()
if ($dnsAtual.Count -gt 0) { $servidores += $dnsAtual[0] }
$servidores += '1.1.1.1', '8.8.8.8'
$resDns = foreach ($srv in ($servidores | Select-Object -Unique)) {
    $tempos = foreach ($d in $dominios) {
        $falhou = $false
        $ms = (Measure-Command {
            try { Resolve-DnsName -Name $d -Server $srv -DnsOnly -NoHostsFile -QuickTimeout -ErrorAction Stop | Out-Null } catch { $script:falhou = $true }
        }).TotalMilliseconds
        if (-not $falhou) { $ms }
    }
    $tempos = @($tempos)
    [pscustomobject]@{
        Servidor   = $srv
        'Media ms' = if ($tempos.Count) { [math]::Round(($tempos | Measure-Object -Average).Average, 0) } else { $null }
        Falhas     = $dominios.Count - $tempos.Count
    }
}
LogObj ($resDns | Format-Table -AutoSize)
$dnsPrim = $resDns | Select-Object -First 1
$melhor  = $resDns | Where-Object { $null -ne $_.'Media ms' } | Sort-Object 'Media ms' | Select-Object -First 1
if ($dnsPrim.Falhas -gt 0) { Alerta "O DNS atual ($($dnsPrim.Servidor)) falhou em $($dnsPrim.Falhas) de $($dominios.Count) consultas." }
if ($null -ne $dnsPrim.'Media ms' -and $dnsPrim.'Media ms' -gt 100 -and $melhor.Servidor -ne $dnsPrim.Servidor -and $melhor.'Media ms' -lt ($dnsPrim.'Media ms' / 2)) {
    Alerta "DNS atual lento ($($dnsPrim.'Media ms') ms). O $($melhor.Servidor) respondeu em $($melhor.'Media ms') ms; trocar o DNS no roteador deixa a abertura de sites mais rapida."
}

# ---------------------------------------------------------------- 5. consumo de banda neste PC
Secao '5. Consumo de internet NESTE computador'
Log 'Medindo trafego por 10 segundos (nao use a internet durante a medicao)...'
$s1 = Get-NetAdapterStatistics -Name $ifAlias
Start-Sleep -Seconds 10
$s2 = Get-NetAdapterStatistics -Name $ifAlias
$downMbps = [math]::Round((($s2.ReceivedBytes - $s1.ReceivedBytes) * 8 / 10) / 1e6, 2)
$upMbps   = [math]::Round((($s2.SentBytes     - $s1.SentBytes)     * 8 / 10) / 1e6, 2)
Log "Download em segundo plano: $downMbps Mbps   Upload em segundo plano: $upMbps Mbps"
if ($downMbps -gt 2 -or $upMbps -gt 1) {
    Alerta "Este PC esta usando internet sozinho ($downMbps Mbps down / $upMbps Mbps up). Veja os programas abaixo."
}

Log ''
Log 'Programas com mais conexoes abertas na internet:'
$conns = Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue |
         Where-Object { $_.RemoteAddress -notmatch '^(127\.|::1|0\.0\.0\.0|::$)' }
$porProc = $conns | Group-Object OwningProcess | Sort-Object Count -Descending | Select-Object -First 12 | ForEach-Object {
    $proc = Get-Process -Id ([int]$_.Name) -ErrorAction SilentlyContinue
    [pscustomobject]@{ Programa = if ($proc) { $proc.ProcessName } else { "PID $($_.Name)" }; Conexoes = $_.Count }
}
LogObj ($porProc | Format-Table -AutoSize)

$pesados = 'OneDrive', 'Dropbox', 'GoogleDriveFS', 'googledrivesync', 'iCloudDrive', 'iCloudPhotos', 'MEGAsync',
           'qbittorrent', 'utorrent', 'BitTorrent', 'Transmission', 'Deluge', 'vuze', 'tixati',
           'steam', 'steamwebhelper', 'EpicGamesLauncher', 'Battle.net', 'EADesktop', 'Origin', 'upc', 'GalaxyClient',
           'Backblaze', 'bztransmit', 'CrashPlan', 'IDrive', 'Spotify', 'obs64'
$rodando = Get-Process -ErrorAction SilentlyContinue | Where-Object { $pesados -contains $_.ProcessName } | Select-Object -ExpandProperty ProcessName -Unique
if ($rodando) {
    Log "Programas que costumam consumir muita banda e estao abertos: $($rodando -join ', ')"
    if ($rodando | Where-Object { $_ -match 'torrent|Transmission|Deluge|vuze|tixati' }) {
        Alerta 'Cliente de torrent aberto: ele pode saturar a conexao inteira da casa.'
    }
}
try {
    $do = Get-DeliveryOptimizationStatus -ErrorAction Stop | Where-Object { $_.Status -eq 'Downloading' }
    if ($do) {
        Log 'Downloads do Windows Update em andamento:'
        LogObj ($do | Select-Object FileId, FileSize, BytesFromHttp, BytesFromPeers | Format-Table -AutoSize)
        Alerta 'O Windows Update esta baixando atualizacoes agora.'
    }
} catch { }

# ---------------------------------------------------------------- 6. aparelhos na rede
if (-not $Rapido) {
    Secao '6. Aparelhos conectados na rede'
    $base = ($ipLocal -split '\.')[0..2] -join '.'
    Log "Varrendo $base.1 a $base.254 (cerca de 5 segundos)..."
    $tarefas = @{}
    foreach ($n in 1..254) {
        $ip = "$base.$n"
        try { $tarefas[$ip] = (New-Object System.Net.NetworkInformation.Ping).SendPingAsync($ip, 800) } catch { }
    }
    try { [System.Threading.Tasks.Task]::WaitAll([System.Threading.Tasks.Task[]]@($tarefas.Values)) } catch { }
    $vivos = @($tarefas.GetEnumerator() | Where-Object {
        $_.Value.Status -eq 'RanToCompletion' -and $_.Value.Result.Status -eq 'Success' } | ForEach-Object { $_.Key })
    Start-Sleep -Milliseconds 500

    $vizinhos = Get-NetNeighbor -InterfaceIndex $ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {
        $_.IPAddress -like "$base.*" -and $_.IPAddress -notlike '*.255' -and
        $_.State -in 'Reachable', 'Stale', 'Delay', 'Probe', 'Permanent' -and
        $_.LinkLayerAddress -and $_.LinkLayerAddress -notmatch '^(00-00-00-00-00-00|FF-FF-FF-FF-FF-FF)$'
    }
    $macPorIp = @{}
    foreach ($v in $vizinhos) { $macPorIp[$v.IPAddress] = $v.LinkLayerAddress }
    $todosIps = @($vivos + @($macPorIp.Keys) + $ipLocal) | Select-Object -Unique |
                Sort-Object { [int](($_ -split '\.')[3]) }

    $aparelhos = foreach ($ip in $todosIps) {
        $nome = ''
        try {
            $t = [System.Net.Dns]::GetHostEntryAsync($ip)
            if ($t.Wait(1500) -and $t.Result.HostName -ne $ip) { $nome = $t.Result.HostName }
        } catch { }
        $mac = if ($ip -eq $ipLocal) { $adaptador.MacAddress } else { $macPorIp[$ip] }
        $obs = @()
        if ($ip -eq $gateway) { $obs += 'ROTEADOR' }
        if ($ip -eq $ipLocal) { $obs += 'este PC' }
        if ($mac -and $mac.Length -ge 2 -and '26AE'.Contains($mac.Substring(1, 1).ToUpper())) { $obs += 'MAC privado (celular/tablet)' }
        [pscustomobject]@{ IP = $ip; Nome = $nome; MAC = $mac; Obs = ($obs -join ', ') }
    }
    $aparelhos = @($aparelhos)
    LogObj ($aparelhos | Format-Table -AutoSize)
    Log "Total encontrado: $($aparelhos.Count) aparelhos (celulares em repouso as vezes nao aparecem)."
    Log 'Confira se reconhece todos. Aparelho estranho = troque a senha do Wi-Fi (use WPA2/WPA3).'
    if ($aparelhos.Count -ge 20) {
        Alerta "Ha $($aparelhos.Count) aparelhos na rede. Roteadores simples de operadora ficam lentos com muitos aparelhos ao mesmo tempo."
    }
}

# ---------------------------------------------------------------- 7. roteador (pagina de administracao)
Secao '7. Identificacao do roteador'
foreach ($porta in 80, 443) {
    $tcp = New-Object System.Net.Sockets.TcpClient
    try {
        $ok = $tcp.BeginConnect($gateway, $porta, $null, $null).AsyncWaitHandle.WaitOne(1500)
        Log ("Porta {0}: {1}" -f $porta, $(if ($ok -and $tcp.Connected) { 'aberta' } else { 'fechada' }))
    } catch { Log "Porta ${porta}: fechada" } finally { $tcp.Close() }
}
try {
    $resp = Invoke-WebRequest -Uri "http://$gateway/" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    $titulo = if ($resp.Content -match '<title[^>]*>\s*([^<]{1,120})') { $Matches[1].Trim() } else { '' }
    Log "Pagina de administracao: http://$gateway/"
    Log "Servidor: $($resp.Headers['Server'])   Titulo da pagina: $titulo"
} catch {
    $r = $_.Exception.Response
    if ($r) { Log "Pagina de administracao respondeu HTTP $([int]$r.StatusCode). Servidor: $($r.Headers['Server'])" }
    else    { Log "Nao foi possivel abrir http://$gateway/ ($($_.Exception.Message))" }
}
Log 'Dica: entre nessa pagina e verifique (1) ha quanto tempo o roteador esta ligado, (2) se ha atualizacao de firmware,'
Log '      (3) a lista de aparelhos/consumo por aparelho, se o modelo mostrar.'

# ---------------------------------------------------------------- 8. tracert e velocidade
if (-not $Rapido) {
    Secao '8. Caminho ate a internet (tracert)'
    Log 'Executando tracert ate 8.8.8.8 (pode levar ~1 minuto)...'
    LogObj ((tracert -d -h 15 -w 800 8.8.8.8) | Out-String)

    Secao '9. Teste de velocidade de download'
    try {
        $url = 'https://speed.cloudflare.com/__down?bytes=25000000'
        $wc  = New-Object System.Net.WebClient
        $sw  = [System.Diagnostics.Stopwatch]::StartNew()
        $dados = $wc.DownloadData($url)
        $sw.Stop()
        $mbps = [math]::Round(($dados.Length * 8 / 1e6) / $sw.Elapsed.TotalSeconds, 1)
        Log "Baixou $([math]::Round($dados.Length / 1e6, 1)) MB em $([math]::Round($sw.Elapsed.TotalSeconds, 1)) s = ~$mbps Mbps"
        Log 'Compare com a velocidade do seu plano. Abaixo de ~60% do plano (no cabo) vale reclamar com a operadora.'
        $dados = $null
    } catch {
        Log "Teste de velocidade falhou: $($_.Exception.Message)"
    }
}

# ---------------------------------------------------------------- resumo
Secao 'RESUMO - possiveis causas de lentidao'
if ($Alertas.Count -eq 0) {
    Log 'Nenhum problema evidente encontrado neste momento. Se a lentidao e intermitente, rode o script'
    Log 'de novo exatamente quando a internet estiver lenta.'
} else {
    $i = 1
    foreach ($a in $Alertas) { Log ("{0,2}. {1}" -f $i, $a); $i++ }
}
Log ''
Log 'Dicas gerais: reinicie o roteador se ele estiver ligado ha semanas; mantenha-o em local alto, central e aberto;'
Log 'longe de micro-ondas, espelhos, aquarios e paredes grossas.'
Log ''
Write-Host "Relatorio completo salvo em: $OutFile" -ForegroundColor Green
