@echo off
chcp 65001 >nul
cd /d "C:\Users\Кира\Documents\telegram eng bot"

echo Git: настройка имени и почты...
git config --global user.email "lapiki.alex@gmail.com"
git config --global user.name "kiralapina"

if not exist ".git" (
    echo Инициализация репозитория...
    git init
)

echo Добавление файлов...
git add .

echo Создание коммита...
git commit -m "Telegram English bot"
if errorlevel 1 echo Нет изменений или уже закоммичено.

git branch -M main

git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo Добавление удалённого репозитория...
    git remote add origin https://github.com/kiralapina/englishwordoftheday.git
)

echo Отправка на GitHub...
git push -u origin main

echo.
echo Готово. Репозиторий: https://github.com/kiralapina/englishwordoftheday
pause
