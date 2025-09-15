# Проект 'document-processing-service' - сервис обработки загружаемых документов 

Проект 'document-processing-service' - бэкенд-часть веб-приложения.


## Техзадание и задачи проекта

Необходимо создать сервис для обработки загружаемых документов. Сервис должен 
позволять зарегистрированным пользователям загружать документы через API. 
При загрузке документа администратор платформы должен получать уведомление по 
электронной почте. 
Администратор сможет просматривать, подтверждать или отклонять загруженные 
документы через Django admin. 
После подтверждения или отклонения документа пользователю, загрузившему документ, 
должно приходить уведомление по электронной почте. 

Для обработки уведомлений необходимо использовать систему очередей.

### Задача

1. Создать API для загрузки документов зарегистрированными пользователями.
2. Настроить уведомление администратора по электронной почте при загрузке нового документа.
3. Добавить в Django admin быстрые действия для подтверждения или отклонения загруженных документов.
4. Настроить отправку уведомлений по электронной почте пользователю, когда его документ подтвержден или отклонен.
5. Реализовать систему очередей для отправки уведомлений.
 

### Технические требования:

1. **Фреймворк**: 
   - Использовать фреймворк Django и Django Rest Framework (DRF) для реализации проекта.
2. **База данных**: 
   - Использовать PostgreSQL для хранения данных.
3. **Контейнеризация**: 
   - Использовать Docker и Docker compose для контейнеризации приложения.
4. **Очередь сообщений**: 
   - Использовать Celery или другую систему очередей для отправки уведомлений.
5. **Отправка уведомлений**: 
   - Настроить отправку уведомлений по электронной почте с использованием Django.
6. **Документация**: 
   - В корне проекта должен быть файл README.md с описанием структуры проекта и инструкциями по установке и запуску.
   - Реализовать автогенерируемую документацию API с использованием Swagger.
7. **Качество кода**: 
   - Соблюдать стандарты PEP8.
   - Весь код должен храниться в удаленном Git репозитории.
8. **Тестирование**: 
   - Код должен быть покрыт тестами с покрытием не менее 75%.


## Локальная установка и запуск проекта через Docker Compose

1. Клонируйте репозиторий:
```
git clone https://github.com/Nefertitu/document-processing-service
```
или
```
git clone git@github.com:Nefertitu/document-processing-service.git
```

```
cd document-processing-service
```

2. Скопируйте `.env.example` в `.env` и заполните переменные окружения:
   ```
   cp .env.sample .env
   ```
   
2. Запустите проект:
    ```
    docker-compose build --no-cache
    docker-compose up -d
    ```
   
3. Проверьте работоспособность (проверка логов):

- Откройте в браузере: http://localhost:8000

- База данных: 
```
   docker-compose logs db

```
```
  docker-compose exec db psql -U your_user -d your_db
```

- Redis:
```
   docker-compose logs redis
```
```
   docker-compose exec redis redis-cli ping
```

- Celery: 
```
   docker-compose logs celery
```
```
   docker-compose exec celery celery -A config status

```


- Celery Beat: 
```
   docker-compose logs celery-beat
```

- Выполните миграции и создайте суперпользователя:
```
docker-compose exec web python manage.py migrate
```
```
docker-compose exec web python manage.py csu
```
- Откройте в браузере: http://localhost:8000/admin/


## Настройка виртуальной машины (предварительная подготовка для деплоя):

** Предварительные требования:
- Yandex Cloud аккаунт
- Доступ по SSH
- Ubuntu 22.04 LTS или новее

1. Пошаговая настройка

* Подключение к VM:
```
ssh username@your-vm-ip
```
* Обновление системы
```
sudo apt update && sudo apt upgrade -y
```
* Установка Docker
```
(sudo apt install docker.io docker-compose-plugin -y)
установка отдельно:
sudo apt install docker.io -y
sudo apt-get install -y curl
sudo curl -L "https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
docker-compose --version
sudo systemctl enable docker
sudo systemctl start docker
```
* Установка Python
```
sudo apt install python3 python3-pip python3-venv -y
```
* Установка Poetry
```
curl -sSL https://install.python-poetry.org | python3 -
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```
* Настройка прав
```
sudo usermod -aG docker $USER
newgrp docker
```

##  Автоматический деплой на сервер через GitHub Actions

При push в ветку `development` автоматически запускается CI/CD pipeline который:

✅ Тестирует код
✅ Собирает Docker образы  
✅ Деплоит на сервер
✅ Применяет миграции
✅ Собирает статические файлы
✅ Перезапускает сервисы

*Подробнее в [.github/workflows/ci.yml](.github/workflows/ci.yml)*


1. Форкните репозиторий
Перейдите на https://github.com/Nefertitu/document-processing-service и нажмите "Fork"

2. Настройте сервер (Docker + Git)
```
ssh your_username@your_server_ip
```

3. Установите Docker и Git:
```
sudo apt update && sudo apt install docker.io docker-compose-plugin git -y
sudo usermod -aG docker $USER
newgrp docker
```
4. Настройте секреты в GitHub:
* В вашем форкнутом репозитории перейдите в Settings → Secrets → Actions
* Добавьте следующие секреты:
- DJANGO_SECRET_KEY - секретный ключ Django, можно сгенерировать: openssl rand -base64 32
- DOCKER_HUB_TOKEN - Токен из Docker Hub account settings
- DOCKER_HUB_USERNAME - Username из Docker Hub account settings
- SSH_USER - имя пользователя на сервере
- SERVER_IP - IP-адрес вашего сервера
- SSH_KEY - приватный SSH ключ
- POSTGRES_USER - postgres (или ваше значение)
- POSTGRES_PASSWORD - ваш_пароль
- POSTGRES_DB - docs_processing
- POSTGRES_PORT - 5432
- POSTGRES_SUPERUSER_PASSWORD - postgres

5. Создание суперпользователя:

* Данные по умолчанию:
- **Email**: `superuser@example.com`
- **Password**: `123qwer`

* Для изменения данных:
Заполните в файле `.env` (см. шаблон '.env.sample'):
```
SUPERUSER_EMAIL=your_email@example.com
SUPERUSER_PASSWORD=your_secure_password
```
6. Проверка работоспособности:
* После деплоя проверьте:
- Статус контейнеров
```
docker-compose ps
```
- Логи приложения
```
docker-compose logs web
```

- Проверка статистических файлов
* Посмотрите что в папке staticfiles
```
docker compose exec web ls -la /app/staticfiles/
```
* Проверьте доступность через браузер
```
curl -I http://your-server-ip/static/admin/css/base.css
```
7. Доступ к админке:

* Для первого входа выполните команду для создания суперпользователя:
```
docker-compose exec web python manage.py csu
```
* Откройте в браузере: http://your-server-ip/admin/

8. Проверка эндпоинтов:

- Проверка корневого URL
```
curl http://your-server-ip/
```
- JWT аутентификация
* Получение JWT токена
```
curl -X POST http://89.169.166.189/users/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"superuser@example.com","password":"123qwer"}'
```
* Обновление токена  
```
curl -X POST http://89.169.166.189/users/token/refresh/ \
  -H "Content-Type: application/json" \
  -d '{"refresh":"your_refresh_token"}'
```
- Регистрация
```
curl -X POST http://89.169.166.189/users/register/ \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"testpassword","password2":"testpassword"}'
```
- Просмотр пользователей:
```
curl http://89.169.166.189/users/ \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

## Приложение развернуто на VM на server-ip: http://51.250.110.74/ 
