## Dev Setup Docker
  1. Install Docker
  1. cd $PROJECT_ROOT
  1. docker-compose up (skip if using VSCode integration)
  1. Use docker to shell into device container
  1. Run `PGPASSWORD=pass psql -U usr -h db liftaidb -f ./global_install.sql`

### VSCode Integration (Recommended)
  1. Install Remote - Containers VSCode Extension
  1. Open command palette (CMD + SHIFT + P)
  1. Choose "Remote Containers: Open Folder In Container"
  1. Choose Project Root
  1. Choose "From docker-compose.yml"
  1. Choose "device" service
  1. Open terminal in VSCode and run `PGPASSWORD=pass psql -U usr -h db liftaidb -f ./global_install.sql`
  1. Recommended Extensions
      - Python
      - Visual Studio Intellicode
      - Code Spell Checker
      - GitLens
      - Live Share Extension Pack (Pair programming)

### Running the tests in Docker

#### Test Only:
`LIFTAI_DB_HOST=db python test.py`

#### With Coverage:
  1. `pip install coverage`
  1. `LIFTAI_DB_HOST=db coverage run test.py`
  1. `coverage report`

#### Customizing what tests run
In order to customize what is run you can comment out test modules in `test.py`.

Alternatively you can only run the test code in the module you're interested in. For example: `LIFTAI_DB_HOST=db python ./altimeter/altimeter/tests.py` However `test.py` changes some environment variables which make the tests run reliably in docker. Depending on the specific module that is being executed for tests additional flags may need to be added to the command line.


## Dev Setup (Legacy)

[![Build Status](https://travis-ci.com/LiftAI/python-development.svg?token=CXQ58pzWLJ31CyKGBdpV&branch=master)](https://travis-ci.com/LiftAI/python-development)

DATABASE INSTALL

To install Postgress on Rasppberry Pi 3 with Raspbian

1. Install DB:
`
sudo apt install postgresql libpq-dev postgresql-client postgresql-client-common -y
`
2. switch user to postgres: 
`
sudo su postgres
`
3. createuser a DB with name 'usr':
`
createuser usr -P --interactive
`
set password pass
select n for superuser, and y for the next two questions.
4. connect to postgres and 
`
psql
`
5. create a database with name liftaidb in psql
`
create database liftaidb;
`

To install DB to the Developer's machine Docker can be used

1. Install Docker to ease Postgres Installation
2. start docker container:
`docker run --name sqlalchemy-orm-psql \
    -e POSTGRES_PASSWORD=pass \
    -e POSTGRES_USER=usr \
    -e POSTGRES_DB=liftaidb \
    -p 5432:5432 \
    -d postgres
`

CONFIGURE PYTHON DEVELOPMENT ENVIRONMENT:

1. get source code
2. install virtualenv with pip
`
sudo pip install virtualenv
`
3. create a folder for virtualenvs
`
mkdir /home/pi/.virtualenvs/
`
4. create a new virtualenv with python3
`
virtualenv -p python3 /home/pi/.virtualenvs/liftai
`
5. activate virtualenv
`
source /home/pi/.virtualenvs/liftai/bin/activate
`
6. go to python-development folder
`
cd python-development
`
7. install all requirements
`
pip install -r requirements.txt
`
8. (optionally) install psycopg2 system wide
`
sudo apt-get install python-psycopg2
`

DEPLOY TO RASPBERRY PI:

1. Connect to raspberry pi via ssh
2. Get the code locally
3. On a clean raspbian install execute `.deploy_clean_raspbian.sh`
4. reboot the board
