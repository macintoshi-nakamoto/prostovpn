sc stop AmneziaWGTunnel$NexaVPN
sc delete AmneziaWGTunnel$NexaVPN
taskkill /IM "NexaVPN-service.exe" /F
taskkill /IM "NexaVPN.exe" /F
exit /b 0
