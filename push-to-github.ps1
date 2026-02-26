# Скрипт: отправить проект в GitHub (kiralapina/englishwordoftheday)
# Запуск: правый клик по файлу → "Выполнить с помощью PowerShell"
# Или в PowerShell: cd "C:\Users\Кира\Documents\telegram eng bot"; .\push-to-github.ps1

$ErrorActionPreference = "Stop"
$repoUrl = "https://github.com/kiralapina/englishwordoftheday.git"
$projectPath = "C:\Users\Кира\Documents\telegram eng bot"

Set-Location $projectPath

Write-Host "Git: настройка имени и почты..." -ForegroundColor Cyan
git config --global user.email "lapiki.alex@gmail.com"
git config --global user.name "kiralapina"

if (-not (Test-Path ".git")) {
    Write-Host "Инициализация репозитория..." -ForegroundColor Cyan
    git init
}

Write-Host "Добавление файлов..." -ForegroundColor Cyan
git add .

Write-Host "Создание коммита..." -ForegroundColor Cyan
git commit -m "Telegram English bot"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Нет изменений для коммита или уже всё закоммичено — продолжаю push." -ForegroundColor Yellow
}

git branch -M main

$remote = git remote get-url origin 2>$null
if (-not $remote) {
    Write-Host "Добавление удалённого репозитория..." -ForegroundColor Cyan
    git remote add origin $repoUrl
} else {
    Write-Host "Remote origin уже задан: $remote" -ForegroundColor Gray
}

Write-Host "Отправка на GitHub..." -ForegroundColor Cyan
git push -u origin main

Write-Host "Готово. Репозиторий: https://github.com/kiralapina/englishwordoftheday" -ForegroundColor Green
