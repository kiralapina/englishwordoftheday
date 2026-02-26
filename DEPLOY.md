# Запуск бота на alwaysdata (сервер)

## 1. Подготовка кода (локально)

- Закоммитьте проект в Git (опционально, но удобно):
  ```bash
  git init
  git add .
  git commit -m "Deploy bot"
  ```
- Или просто запакуйте папку с ботом (без `__pycache__`, `logs`, `.env` — на сервере создадите свой `.env`).

## 2. Доступ к серверу alwaysdata

- В панели alwaysdata: **Advanced** → **SSH** — проверьте, что SSH включён.
- Подключитесь по SSH (логин и хост из панели):
  ```bash
  ssh ваш_логин@ssh-ваш_логин.alwaysdata.net
  ```

## 3. Загрузка файлов на сервер

**Вариант А — через Git (если репозиторий на GitHub/GitLab):**
```bash
cd ~/admin
git clone https://github.com/ВАШ_ЛОГИН/telegram-eng-bot.git
cd telegram-eng-bot
```

**Вариант Б — через SFTP/файловый менеджер alwaysdata:**  
Скопируйте в каталог пользователя (например `~/admin/telegram-eng-bot/`) файлы:
- `bot.py`, `database.py`, `word_api.py`
- папку `data/`
- `requirements.txt`
- не копируйте `.env` с паролями — создадите его на сервере.

## 4. Окружение и зависимости на сервере

```bash
cd ~/admin/telegram-eng-bot   # или ваш путь
python3 -m venv venv
source venv/bin/activate      # Linux/macOS на сервере
pip install -r requirements.txt
```

## 5. Переменные окружения на сервере

Создайте файл `.env` в папке бота:
```bash
nano .env
```
Содержимое (подставьте свои значения):
```
BOT_TOKEN=ваш_токен_бота
PGHOST=postgresql-superwomansocool.alwaysdata.net
PGPORT=5432
PGDATABASE=superwomansocool_test
PGUSER=superwomansocool
PGPASSWORD=ваш_пароль
```
Сохраните (Ctrl+O, Enter, Ctrl+X).

## 6. Запуск бота и работа в фоне

Однократный запуск (проверка):
```bash
source venv/bin/activate
python bot.py
```
Если в консоли видно «Бот успешно запущен» — остановите (Ctrl+C) и запустите в фоне:

**Через nohup (простой вариант):**
```bash
source venv/bin/activate
nohup python bot.py > bot.log 2>&1 &
```
Просмотр логов: `tail -f bot.log`

**Через screen (удобно переподключаться):**
```bash
screen -S bot
source venv/bin/activate
python bot.py
```
Отсоединиться: Ctrl+A, затем D. Вернуться: `screen -r bot`

## 7. Автозапуск при перезагрузке сервера (опционально)

В панели alwaysdata: **Advanced** → **Cron** — добавьте задачу, которая при старте системы запускает бота (или используйте раздел **Processes**, если он есть в вашем тарифе).

Пример скрипта запуска `~/admin/telegram-eng-bot/start_bot.sh`:
```bash
#!/bin/bash
cd ~/admin/telegram-eng-bot
source venv/bin/activate
nohup python bot.py >> bot.log 2>&1 &
```
Сделайте исполняемым: `chmod +x start_bot.sh`. Вызывайте его из cron при загрузке (@reboot) или вручную после перезапуска сервера.

---

## 8. Как обновлять бота на сервере

### Вариант А: Вручную по SSH

После того как вы что-то изменили и сделали `git push` в GitHub:

```bash
ssh ваш_логин@ssh-ваш_логин.alwaysdata.net
cd ~/admin/telegram-eng-bot
chmod +x scripts/update_and_restart.sh
./scripts/update_and_restart.sh
```

Скрипт подтянет изменения из Git и перезапустит бота.

### Вариант Б: Автоматически при каждом push (GitHub Actions)

При каждом `git push` в ветку `main` сервер сам обновит код и перезапустит бота.

1. **Создайте SSH-ключ для деплоя** (на своём компьютере, один раз):
   ```bash
   ssh-keygen -t ed25519 -C "deploy" -f deploy_key -N ""
   ```
   Появятся файлы `deploy_key` (приватный) и `deploy_key.pub` (публичный).

2. **На сервере** добавьте публичный ключ в `~/.ssh/authorized_keys`:
   ```bash
   ssh ваш_логин@ssh-ваш_логин.alwaysdata.net
   mkdir -p ~/.ssh
   echo "содержимое deploy_key.pub" >> ~/.ssh/authorized_keys
   ```

3. **В GitHub** в репозитории: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**. Добавьте три секрета:
   - `SERVER_HOST` — хост сервера, например `ssh-ваш_логин.alwaysdata.net`
   - `SERVER_USER` — ваш SSH-логин на alwaysdata
   - `SSH_PRIVATE_KEY` — **целиком** скопированное содержимое файла `deploy_key` (приватный ключ)

4. В файле **`.github/workflows/deploy.yml`** в секции `script:` проверьте путь к проекту на сервере. Сейчас там:
   ```yaml
   cd ~/admin/telegram-eng-bot || cd ~/telegram-eng-bot
   ```
   Если бот у вас лежит в другой папке — замените на свой путь.

После этого при каждом `git push origin main` GitHub Actions подключится к серверу и выполнит обновление и перезапуск.

---

После этого **не запускайте бота локально** с тем же токеном — иначе будет конфликт (Conflict). Работать должен только один экземпляр — на сервере.
