@echo off
cd /d "%~dp0"
dotnet run --project "..\xrce_csharp_agent\FishBotXrceAgent.csproj" -c Release -- --agent-only
pause
