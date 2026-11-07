param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('status', 'wifi-on', 'wifi-off', 'bluetooth-on', 'bluetooth-off', 'airplane-on', 'airplane-off', 'airplane-toggle')]
    [string]$Azione
)

$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
Add-Type -AssemblyName System.Runtime.WindowsRuntime

function Attendi-WinRT {
    param(
        [Parameter(Mandatory = $true)]$Operazione,
        [Parameter(Mandatory = $true)][Type]$TipoRisultato
    )

    $metodoAsTask = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq 'AsTask' -and
            $_.IsGenericMethodDefinition -and
            $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        } | Select-Object -First 1

    if (-not $metodoAsTask) {
        throw 'Impossibile collegare le operazioni radio di Windows.'
    }

    $task = $metodoAsTask.MakeGenericMethod($TipoRisultato).Invoke($null, @($Operazione))
    return $task.GetAwaiter().GetResult()
}

function Prendi-Radio {
    $tipoRadio = [Windows.Devices.Radios.Radio, Windows.Devices.Radios, ContentType=WindowsRuntime]
    $tipoOperazione = $tipoRadio.GetMethod('GetRadiosAsync').ReturnType
    $tipoRisultato = $tipoOperazione.GenericTypeArguments[0]
    $operazione = $tipoRadio.GetMethod('GetRadiosAsync').Invoke($null, @())
    $risultato = Attendi-WinRT -Operazione $operazione -TipoRisultato $tipoRisultato
    $elenco = [System.Collections.Generic.List[object]]::new()
    foreach ($radio in $risultato) {
        $elenco.Add($radio)
    }
    # Niente virgola: PowerShell deve emettere le radio una alla volta nel pipeline.
    return $elenco.ToArray()
}

function Imposta-Radio {
    param(
        [Parameter(Mandatory = $true)]$Radio,
        [Parameter(Mandatory = $true)][bool]$Attivo
    )

    $tipoRadio = [Windows.Devices.Radios.Radio, Windows.Devices.Radios, ContentType=WindowsRuntime]
    $statoRichiesto = if ($Attivo) {
        [Windows.Devices.Radios.RadioState]::On
    }
    else {
        [Windows.Devices.Radios.RadioState]::Off
    }

    if ($Radio.State.ToString() -eq $statoRichiesto.ToString()) {
        return $true
    }

    $tipoRisultato = $tipoRadio.GetMethod('SetStateAsync').ReturnType.GenericTypeArguments[0]
    $operazione = $Radio.SetStateAsync($statoRichiesto)
    $risultato = Attendi-WinRT -Operazione $operazione -TipoRisultato $tipoRisultato
    if ($risultato.ToString() -ne 'Allowed') {
        return $false
    }

    for ($tentativo = 0; $tentativo -lt 20; $tentativo++) {
        Start-Sleep -Milliseconds 150
        if ($Radio.State.ToString() -eq $statoRichiesto.ToString()) {
            return $true
        }
    }
    return $false
}

function Scrivi-Risultato {
    param([bool]$Ok, [string]$Messaggio)
    [pscustomobject]@{ Ok = $Ok; Messaggio = $Messaggio } | ConvertTo-Json -Compress
}

function Salva-StatoAereo {
    param($Stato)
    $projectRoot = Split-Path -Parent $PSScriptRoot
    $cartellaLog = Join-Path $projectRoot 'logs'
    if (-not (Test-Path -LiteralPath $cartellaLog)) {
        New-Item -ItemType Directory -Path $cartellaLog -Force | Out-Null
    }
    $percorso = Join-Path $cartellaLog 'radio-airplane-state.json'
    $Stato | ConvertTo-Json -Compress | Set-Content -LiteralPath $percorso -Encoding UTF8
}

try {
    $tipoRadio = [Windows.Devices.Radios.Radio, Windows.Devices.Radios, ContentType=WindowsRuntime]
    $accessoOperazione = $tipoRadio.GetMethod('RequestAccessAsync').Invoke($null, @())
    $tipoAccesso = $tipoRadio.GetMethod('RequestAccessAsync').ReturnType.GenericTypeArguments[0]
    $accesso = Attendi-WinRT -Operazione $accessoOperazione -TipoRisultato $tipoAccesso
    if ($accesso.ToString() -ne 'Allowed') {
        throw "Windows non ha autorizzato il controllo delle radio (stato: $accesso)."
    }

    $radios = @(Prendi-Radio)
    $wifi = $radios | Where-Object { $_.Kind.ToString() -eq 'WiFi' } | Select-Object -First 1
    $bluetooth = $radios | Where-Object { $_.Kind.ToString() -eq 'Bluetooth' } | Select-Object -First 1
    $fileStatoAereo = Join-Path (Split-Path -Parent $PSScriptRoot) 'logs\radio-airplane-state.json'
    $statoSalvato = $null
    if (Test-Path -LiteralPath $fileStatoAereo) {
        $statoSalvato = Get-Content -LiteralPath $fileStatoAereo -Raw | ConvertFrom-Json
    }

    if ($Azione -eq 'status') {
        $aereoAttivo = if ($statoSalvato) { [bool]$statoSalvato.Attiva } else { $wifi.State.ToString() -eq 'Off' -and $bluetooth.State.ToString() -eq 'Off' }
        [pscustomobject]@{
            Ok = $true
            Messaggio = 'Stato radio letto.'
            WiFi = $wifi.State.ToString() -eq 'On'
            Bluetooth = $bluetooth.State.ToString() -eq 'On'
            Airplane = $aereoAttivo
        } | ConvertTo-Json -Compress
        exit 0
    }

    if ($Azione -like 'airplane-*') {
        if (-not $wifi -or -not $bluetooth) {
            throw 'Windows non espone entrambe le radio Wi-Fi e Bluetooth necessarie per la modalità aereo.'
        }

        $aereoAttivo = $false
        if ($statoSalvato) {
            $aereoAttivo = [bool]$statoSalvato.Attiva
        }
        elseif ($wifi.State.ToString() -eq 'Off' -and $bluetooth.State.ToString() -eq 'Off') {
            $aereoAttivo = $true
        }

        $azioneAereo = $Azione.Substring('airplane-'.Length)
        if ($azioneAereo -eq 'toggle') {
            $azioneAereo = if ($aereoAttivo) { 'off' } else { 'on' }
        }

        if ($azioneAereo -eq 'on') {
            $wifiPrecedente = if ($aereoAttivo) { [bool]$statoSalvato.WiFi } else { $wifi.State.ToString() -eq 'On' }
            $bluetoothPrecedente = if ($aereoAttivo) { [bool]$statoSalvato.Bluetooth } else { $bluetooth.State.ToString() -eq 'On' }
            $nuovoStato = [pscustomobject]@{
                Attiva = $true
                WiFi = $wifiPrecedente
                Bluetooth = $bluetoothPrecedente
            }
            Salva-StatoAereo $nuovoStato
            $wifiOk = Imposta-Radio -Radio $wifi -Attivo $false
            $bluetoothOk = Imposta-Radio -Radio $bluetooth -Attivo $false
            if (-not ($wifiOk -and $bluetoothOk)) {
                if ($nuovoStato.WiFi) { $null = Imposta-Radio -Radio $wifi -Attivo $true }
                if ($nuovoStato.Bluetooth) { $null = Imposta-Radio -Radio $bluetooth -Attivo $true }
                Remove-Item -LiteralPath $fileStatoAereo -Force -ErrorAction SilentlyContinue
                throw 'Windows non ha confermato lo spegnimento di Wi-Fi e Bluetooth.'
            }
            Scrivi-Risultato $true 'Modalità aereo attivata: Wi-Fi e Bluetooth spenti.'
            exit 0
        }

        $wifiDaRipristinare = if ($statoSalvato) { [bool]$statoSalvato.WiFi } else { $true }
        $bluetoothDaRipristinare = if ($statoSalvato) { [bool]$statoSalvato.Bluetooth } else { $true }
        $wifiOk = Imposta-Radio -Radio $wifi -Attivo $wifiDaRipristinare
        $bluetoothOk = Imposta-Radio -Radio $bluetooth -Attivo $bluetoothDaRipristinare
        if (-not ($wifiOk -and $bluetoothOk)) {
            throw 'Windows non ha confermato il ripristino delle radio Wi-Fi e Bluetooth.'
        }
        Remove-Item -LiteralPath $fileStatoAereo -Force -ErrorAction SilentlyContinue
        Scrivi-Risultato $true 'Modalità aereo disattivata: stato precedente delle radio ripristinato.'
        exit 0
    }

    $isWifi = $Azione.StartsWith('wifi-')
    $radioScelta = if ($isWifi) { $wifi } else { $bluetooth }
    $attivo = $Azione.EndsWith('-on')
    if (-not $radioScelta) {
        throw "Windows non espone una radio $(if ($isWifi) { 'Wi-Fi' } else { 'Bluetooth' }) controllabile."
    }
    if (-not (Imposta-Radio -Radio $radioScelta -Attivo $attivo)) {
        throw "Windows non ha confermato il cambio di stato della radio $(if ($isWifi) { 'Wi-Fi' } else { 'Bluetooth' })."
    }

    # Se Onyx ha attivato la modalità aereo, conserva l'ultima scelta esplicita
    # dell'utente per quella radio e la ripristina quando la modalità viene tolta.
    if ((Test-Path -LiteralPath $fileStatoAereo) -and $statoSalvato -and $statoSalvato.Attiva) {
        if ($isWifi) { $statoSalvato.WiFi = $attivo } else { $statoSalvato.Bluetooth = $attivo }
        Salva-StatoAereo $statoSalvato
    }

    $nomeRadio = if ($isWifi) { 'Wi-Fi' } else { 'Bluetooth' }
    $stato = if ($attivo) { 'attivato' } else { 'spento' }
    Scrivi-Risultato $true "$nomeRadio $stato."
}
catch {
    Scrivi-Risultato $false $_.Exception.Message
    exit 1
}
