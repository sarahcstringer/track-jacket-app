#!/bin/bash
set -x .
sed '1s/$/ aws/' -i /etc/hosts
apt-get update
apt-get upgrade
apt-get install -y python-virtualenv
apt-get install -y build-essential python-dev
apt-get install -y postgresql postgresql-client
sudo -u postgres createuser -s ubuntu
sudo -u postgres createuser root
apt-get install -y postgresql-server-dev-10
apt-get install -y postgresql-contrib
apt-get install -y python3.8 python3.8-dev
apt-get install -y python3-pip
apt-get install -y nginx
cd /home/ubuntu/
git clone https://github.com/sarahcstringer/track-jacket-app.git
cd track-jacket-app
pip3 install -r requirements.txt
createdb telephone-pictionary
sudo rm /etc/nginx/sites-enabled/default
sudo cp conf/nginx.conf /etc/nginx/sites-enabled/nginx.conf
sudo systemctl reload nginx
sudo cp conf/app.service /etc/systemd/system/app.service
sudo systemctl enable app
sudo systemctl start app
