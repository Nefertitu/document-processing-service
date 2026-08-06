test:
	python manage.py test --settings=config.local_settings

coverage:
	coverage run --source='.' manage.py test --settings=config.local_settings
	coverage report
	coverage html

migrate:
	python manage.py migrate --settings=config.local_settings

makemigrations:
	python manage.py makemigrations --settings=config.local_settings