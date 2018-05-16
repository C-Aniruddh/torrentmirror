from flask import Flask, render_template, url_for, request, session, redirect, send_from_directory, jsonify
import os
from celery import Celery
from pyaria2 import PyAria2
from flask_pymongo import PyMongo
import bcrypt
import datetime
import json
import re
import time
import subprocess
import threading

app = Flask(__name__)

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_FOLDER = os.path.join(APP_ROOT, 'static/downloads')

app.config['MONGO_DBNAME'] = 'torrentmirror'
app.config['MONGO_URI'] = 'mongodb://localhost:27017/torrentmirror'
app.config['DOWNLOAD_FOLDER'] = DOWNLOAD_FOLDER
app.secret_key = 'mysecret'


mongo = PyMongo(app)
client = PyAria2('localhost', 6000)

def make_celery(app):
    celery = Celery(app.import_name, backend=app.config['CELERY_RESULT_BACKEND'],
                    broker=app.config['CELERY_BROKER_URL'])
    celery.conf.update(app.config)
    TaskBase = celery.Task
    class ContextTask(TaskBase):
        abstract = True
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return TaskBase.__call__(self, *args, **kwargs)
    celery.Task = ContextTask
    return celery

# App routes 

# Index
@app.route('/', methods=['POST', 'GET'])
def index():
    if 'username' in session:
        users = mongo.db.users
        user_result = users.find_one({'name':session['username']})
        user_fullname = user_result['fullname']
        downloads = mongo.db.downloads
        all_downloads = downloads.find({})
        downloadlist = range(0, all_downloads.count(), 1)
        download_names = []
        download_types = []
        gdrive_links = []
        if all_downloads.count() > 0:
            for download in all_downloads:
                download_names.append(download['name'])
                if download['download_type'] == 'direct':
                    download_types.append('Direct Download')
                elif download['download_type'] == 'torrent':
                    download_types.append('Torrent Download')
                gdrive_links.append(download['drive_link'])

        return render_template('index.html', user_fullname=user_fullname, downloadlist=downloadlist, download_names=download_names, download_types=download_types, gdrive_links=gdrive_links)
    else:
        return redirect('/userlogin')  
      
@app.route('/myuploads', methods=['POST', 'GET'])
def myuploads():
    if 'username' in session:
        users = mongo.db.users
        user_result = users.find_one({'name':session['username']})
        user_fullname = user_result['fullname']
        downloads = mongo.db.downloads
        all_downloads = downloads.find({'added_by' : session['username']}, {'name': True, 'download_type': True, 'drive_link': True, '_id': False})
        downloadlist = range(0, all_downloads.count(), 1)
        download_names = []
        download_types = []
        gdrive_links = []
        if all_downloads.count() > 0:
            for download in all_downloads:
                download_names.append(download['name'])
                if download['download_type'] == 'direct':
                    download_types.append('Direct Download')
                elif download['download_type'] == 'torrent':
                    download_types.append('Torrent Download')
                gdrive_links.append(download['drive_link'])

        return render_template('index.html', user_fullname=user_fullname, downloadlist=downloadlist, download_names=download_names, download_types=download_types, gdrive_links=gdrive_links)
    else:
        return redirect('/userlogin')  

# Add downloads
@app.route('/add_download', methods=['POST', 'GET'])
def add_download():
    if request.method == 'POST':
        if 'username' in session:
            downloads = mongo.db.downloads
            session['upload_gdrive'] = 1
            download_link = request.form['link']
            download_uris = []
            download_uris.append(download_link)
            download_type = request.form['type']
            download_id = str(downloads.find().count() + 1)
            if download_type == 'direct' : 
                this_download_gid = client.addUri(download_uris, dict(dir=app.config['DOWNLOAD_FOLDER']))
            elif download_type == 'torrent' : 
                metadata_gid = client.addUri(download_uris, dict(dir=app.config['DOWNLOAD_FOLDER']))
                metadata_download_result = client.tellStatus(metadata_gid)
                while 'followedBy' not in metadata_download_result:
                    metadata_download_result = client.tellStatus(metadata_gid)
                this_download_gid = metadata_download_result['followedBy'][0]
                print(metadata_gid, this_download_gid)
            downloads.insert({'added_by' : session['username'], 'name' : str(request.form['download_name']), 'identifier' : download_id, 'link' : download_link, 'gid' : this_download_gid, 'drive_link' : 'default','status' : 'started', 'download_type' : str(download_type)})
            redir_uri = '/show_download/%s' % (download_id)
            return redirect(redir_uri)
        else:
            return redirect('/userlogin')

    if 'username' in session:
        users = mongo.db.users
        user_result = users.find_one({'name':session['username']})
        user_fullname = user_result['fullname']
        return render_template('add_download.html', user_fullname=user_fullname)
    else:
        return redirect('/userlogin')  

# Download View
@app.route('/show_download/<identifier>')
def show_download(identifier):
    if 'username' in session:
        users = mongo.db.users
        user_result = users.find_one({'name':session['username']})
        user_fullname = user_result['fullname']

        downloads = mongo.db.downloads
        current_download_result = downloads.find_one({'identifier' : identifier})
        print(current_download_result)
        if current_download_result is None:
            return '404'

        current_download_type = current_download_result['download_type']
        current_download_name = current_download_result['name']
        current_download_gid = current_download_result['gid']
        current_download_status = current_download_result['status']

        return render_template('show_single_download.html', user_fullname=user_fullname, download_name=current_download_name, download_gid=current_download_gid, download_status=current_download_status, identifier=identifier)
        
@app.route('/get_download_status/<download_gid>', methods=['GET'])
def get_download_status(download_gid):
    
    current_download_status = client.tellStatus(download_gid)
    #print(current_download_status)
    completed_length = current_download_status['completedLength']
    total_length = int(current_download_status['totalLength'])
    if total_length != 0:
        completion_percentage = ((int(completed_length)/total_length)*100)
        completion_percentage = "{:.2f}".format(completion_percentage)
        download_speed_bytes = current_download_status['downloadSpeed']
        download_speed_mb = (int(download_speed_bytes)/1000000)
        download_status_str = 'Currently downloading at {:.2f} MB/s'.format(download_speed_mb)
    else:
        completion_percentage = 0
        download_speed_bytes = 0
        download_speed_mb = 0
        download_status_str = 'Waiting for connection'
    
    if int(completed_length)/int(total_length) == 1:
        downloads = mongo.db.downloads
        current_download_result_full = downloads.find_one({'gid': download_gid})
        download_identifier = current_download_result_full['identifier']
        download_status_str = 'Download complete'
        download_file = current_download_status['files'][0]
        download_file_path = download_file['path']
        download_link = current_download_result_full['drive_link']
        if download_link == 'default':
            handleGDriveUpload(download_file_path, download_identifier)    
        downloads.update_one({'gid': download_gid}, {"$set": {'status': 'done'}})

    download_factor = str(int(completed_length)/int(total_length))
    return jsonify(download_speed=download_status_str, completion_percentage=completion_percentage, download_factor=download_factor)


def handleGDriveUpload(filepath, identifier):
    print("UPLOADING TO DRIVE")
    full_output = subprocess.check_output(['gdrive', 'upload', '--patent', '1y1cmx_L_c_pQgAuLvTbVn76EfkwgIL4F',  filepath])
    full_output_str = full_output.decode('utf-8')
    spl1 = full_output_str.split('Uploaded ')
    file_id = spl1[1].split(' at')[0]
    share = subprocess.check_output(['gdrive', 'share', file_id])
    gdrive_link = 'https://drive.google.com/uc?id=%s&export=download'% (file_id)
    downloads = mongo.db.downloads
    downloads.update_one({'identifier': identifier}, {"$set": {'drive_link': gdrive_link}})
    print("UPLOADED AND UPDATED")

@app.route('/get_drive_link/<identifier>', methods=['POST', 'GET'])
def get_drive_link(identifier):
    downloads = mongo.db.downloads
    find_download = downloads.find_one({'identifier': identifier})
    gdrive_link = find_download['drive_link']
    return jsonify(gdrive_link=gdrive_link)
    
# Login and register 
@app.route('/register', methods=['POST', 'GET'])
def register():
    if 'username' in session:
        return redirect('/')
    if request.method == 'POST':
        users = mongo.db.users
        user_fname = request.form.get('name')
        # user_fname = request.form['name']
        user_email = request.form.get('email')
        existing_user = users.find_one({'name': request.form.get('username')})
        if existing_user is None:
            hashpass = bcrypt.hashpw(request.form.get('password').encode('utf-8'), bcrypt.gensalt())
            users.insert(
                {'fullname': user_fname, 'email': user_email, 'name': request.form.get('username'),
                 'user_type': 'worker', 'password': hashpass})
            session['username'] = request.form.get('username')
            return redirect('/')

        return 'A user with that Email id/username already exists'

    return render_template('signup.html')


@app.route('/userlogin', methods=['POST', 'GET'])
def userlogin():
    if 'username' in session:
        return redirect('/')

    return render_template('signin.html')


@app.route('/login', methods=['POST'])
def login():
    users = mongo.db.users
    login_user = users.find_one({'name': request.form['username']})

    if login_user:
        if bcrypt.hashpw(request.form.get('password').encode('utf-8'), login_user['password']) == login_user[
            'password']:
            session['username'] = request.form['username']
            return redirect('/')

    return 'Invalid username/password combination'


@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect('/')


@app.route('/downloads/<filename>')
def downloads(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def page_not_found(e):
    return render_template('500.html'), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0')
