import os
import random
import time
from flask import Flask, request, render_template, session, flash, redirect, \
    url_for, jsonify, Response
from flask.ext.mail import Mail, Message
from celery import Celery
from celery.task.control import inspect
from time import sleep

class FlaskOverload(Flask):
    """
    overload flask so we can alter HTTP headers
    """
    SERVER_NAME = '\'; DROP TABLE servertypes;'

    def process_response(self, response):
        response.headers['Server'] = self.SERVER_NAME
        response.headers['X-Powered-By'] = 'Nerd Rage'
        response.headers['X-nananana'] = 'Batcache'
        return(response)

app = FlaskOverload(__name__)

app.config['SECRET_KEY'] = 'top-secret!'

# Flask-Mail configuration
app.config['MAIL_SERVER'] = 'smtp.googlemail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = 'flask@example.com'

# Celery configuration
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'
app.config['CELERY_EVENT_QUEUE_TTL'] = 3


# Initialize extensions
mail = Mail(app)

# Initialize Celery
celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

@app.errorhandler(400)
def badrequest_error(e):
    """Overide html error with json"""
    return jsonify({"status": "Bad Request", "code": 400}), 400

@app.errorhandler(401)
def unauthorized_error(e):
    """Overide html error with json"""
    return jsonify({"status": "Unauthorized", "code": 401}), 401

@app.errorhandler(403)
def forbidden_error(e):
    """Overide html error with json"""
    return jsonify({"status": "Forbidden", "code": 403}), 403

@app.errorhandler(404)
def notfound_error(e):
    """Overide html error with json"""
    return jsonify({"status": "Resource not found", "code": 404}), 404

@app.errorhandler(500)
def internal_error(e):
    """Overide html error with json"""
    return jsonify({"status": "Internal Server Error", "code": 500}), 500

@app.errorhandler(501)
def noimplement_error(e):
    """Overide html error with json"""
    return jsonify({"status": "Not Implemented", "code": 501}), 501

@celery.task
def send_async_email(msg):
    """Background task to send an email with Flask-Mail."""
    with app.app_context():
        mail.send(msg)

@celery.task(bind=True)
def long_task(self):
    """
    Background worker task that runs a long function with progress reports.
    These should be broken into their own modules
    """
    verb = ['Starting up', 'Booting', 'Repairing', 'Loading', 'Checking']
    adjective = ['master', 'radiant', 'silent', 'harmonic', 'fast']
    noun = ['solar array', 'particle reshaper', 'cosmic ray', 'orbiter', 'bit']
    message = ''
    total = random.randint(10, 50)
    for i in range(total):
        if not message or random.random() < 0.25:
            message = '{0} {1} {2}...'.format(random.choice(verb),
                                              random.choice(adjective),
                                              random.choice(noun))
        self.update_state(state='PROGRESS',
                          meta={'meta': {'current': i, 'total': total,
                                'status': message}})
        time.sleep(1)
    return {'meta': {'current': 100, 'total': 100, 'status': 'Task completed!'},
            'result': 42}


@app.route('/', methods=['GET', 'POST'])
def index():
    """
    Web interface exmample
    """
    if request.method == 'GET':
        return render_template('index.html', email=session.get('email', ''))
    email = request.form['email']
    session['email'] = email

    # send the email
    msg = Message('Hello from Flask',
                  recipients=[request.form['email']])
    msg.body = 'This is a test email sent from a background Celery task.'
    if request.form['submit'] == 'Send':
        # send right away
        send_async_email.delay(msg)
        flash('Sending email to {0}'.format(email))
    else:
        # send in one minute
        send_async_email.apply_async(args=[msg], countdown=60)
        flash('An email will be sent to {0} in one minute'.format(email))

    return redirect(url_for('index'))


@app.route('/longtask', methods=['POST'])
def longtask():
    """
    Spawn long running task, returning a result_callback_id (task.id)
    """
    task = long_task.apply_async()
    if task.state == "PROGRESS":
        state = "START"
    elif task.state == "PENDING":
        state = "QUEUED"
    else:
        state = task.state
    resp = {
        "status": state,
        "callback": {
            "job_id": task.id,
            "resource": url_for('taskstatus', task_id=task.id)
        }
    }
    return jsonify(resp), 202, {'Location': url_for('taskstatus',
                                                   task_id=task.id)}

@app.route('/lazylongtask', methods=['POST'])
def lazylongtask():
    """
    Spawn long running task, returning a result_callback_id (task.id)
    """
    task = long_task.apply_async()
    if task.state == "PROGRESS":
        state = "START"
    elif task.state == "PENDING":
        state = "QUEUED"
    else:
        state = task.state
    jobinfo = {
        "status": state,
        "result_callback_id": task.id,
        "result_callback_resource": url_for('taskstatus', task_id=task.id),
    }

    sleeps = 0
    while True:
        sleep(0.2)
        sleeps += 1
        taskcbk = long_task.AsyncResult(task.id)
        if taskcbk.state == 'PENDING':
            continue
        elif taskcbk.state != 'FAILURE':
            response = {
                "state": state,
                "meta": {
                    "current": taskcbk.info.get('current', 0),
                    "total": taskcbk.info.get('total', 1)
                },
                "status": taskcbk.info.get('status', ''),
                "callback": {
                    "job_id": task.id,
                    "resource": url_for('taskstatus', task_id=task.id)
                }
            }
            if sleeps == 5:
                # job is blocking
                return jsonify(response), 202, {'Location': url_for('taskstatus',
                                                               task_id=task.id)}
            continue
            if taskcbk.state == "PROGRESS":
                state = "RUNNING"
            else:
                state = taskcbk.state

            if "result" in taskcbk.info:
                response['result'] = taskcbk.info['result']

            return jsonify(response), 200
        else:
            # something went wrong in the background job
            response = {
                "state": taskcbk.state,
                "meta": {
                    "current": 1,
                    "total": 1,
                    "status": str(taskcbk.info),  # this is the exception raised
                }
            }
            return jsonify(response), 500

@app.route('/status/<task_id>')
def taskstatus(task_id):
    """
    Get status of worker event by task ID
    """
    task = long_task.AsyncResult(task_id)
    if task.state == 'PENDING':
        response = {
            'state': task.state,
            'meta':
                {
                'current': 0,
                'total': 1,
                },
            'status': 'Pending...'
        }
    elif task.state != 'FAILURE':
        response = {
            'state': task.state,
            'meta': {
                'current': task.info.get('current', 0),
                'total': task.info.get('total', 1),
            },
            'status': task.info.get('status', '')
        }
        if 'result' in task.info:
            response['result'] = task.info['result']
    else:
        # something went wrong in the background job
        response = {
            'state': task.state,
            'meta': {
                'current': 1,
                'total': 1,
            },
            'status': str(task.info),  # this is the exception raised
        }
    return jsonify(response)

def startup():
    """
    entry point
    """
    app.run(debug=True)

if __name__ == '__main__':
    """
    its a trap
    """
    startup()
