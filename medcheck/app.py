from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://meduser:yourpassword@localhost:6432/medcheck'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
db = SQLAlchemy(app)

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])


class Person(db.Model):
    __tablename__ = 'persons'
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, unique=True, nullable=False)
    fio = db.Column(db.String(100), nullable=False)
    birth_date = db.Column(db.DateTime, nullable=True)
    checks = db.relationship('MedicalCheck', backref='person', lazy=True)


class MedicalCheck(db.Model):
    __tablename__ = 'medical_checks'
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey('persons.id'), nullable=False)
    check_date = db.Column(db.DateTime, nullable=False)
    check_type = db.Column(db.String(10), nullable=False)  # "vlek", "kmo", "umo"
    status = db.Column(db.String(20), nullable=True)  # "разрешен" или "запрещен вылет"
    diagnosis = db.Column(db.String(200), nullable=True)
    photo_path = db.Column(db.String(200), nullable=True)

    def get_expiry_date(self):
        if self.check_type in ["kmo", "umo"]:
            return self.check_date + timedelta(days=90)  # 3 месяца для КМО и УМО
        elif self.check_type == "vlek":
            return self.check_date + timedelta(days=365)  # 1 год для ВЛЭК
        return self.check_date

    def get_next_check(self):
        checks = MedicalCheck.query.filter_by(person_id=self.person_id).order_by(MedicalCheck.check_date.desc()).limit(
            4).all()
        if not checks:
            return "vlek", self.check_date  # Первый осмотр — ВЛЭК
        last_check = checks[0]

        # Цикл: ВЛЭК → КМО → УМО → КМО → ВЛЭК
        if len(checks) >= 4 and checks[0].check_type == "kmo" and checks[1].check_type == "umo" and checks[
            2].check_type == "kmo" and checks[3].check_type == "vlek":
            return "vlek", last_check.check_date + timedelta(days=90)
        elif last_check.check_type == "vlek":
            return "kmo", last_check.check_date + timedelta(days=90)
        elif last_check.check_type == "kmo" and (len(checks) == 1 or checks[1].check_type == "vlek"):
            return "umo", last_check.check_date + timedelta(days=90)
        elif last_check.check_type == "umo":
            return "kmo", last_check.check_date + timedelta(days=90)
        return "kmo", last_check.check_date + timedelta(days=90)


with app.app_context():
    db.create_all()
    if Person.query.count() > 0:
        max_number = db.session.query(db.func.max(Person.number)).scalar() or 0
    else:
        max_number = 0
    Person.next_number = max_number + 1


def check_sequence(person):
    checks = sorted(person.checks, key=lambda c: c.check_date)
    if not checks:
        return False  # Нет осмотров — не прошел
    expected_sequence = ["vlek", "kmo", "umo", "kmo"]
    current_date = datetime.now()

    for i, check in enumerate(checks):
        expected_type = expected_sequence[i % 4]
        if check.check_type != expected_type or check.get_expiry_date() < current_date:
            return False  # Неправильный тип или просрочен
    return True


@app.route('/', methods=['GET'])
def index():
    sort_by = request.args.get('sort', 'expiry')
    search_query = request.args.get('search', '').strip()

    if search_query:
        people = Person.query.filter(Person.fio.ilike(f'%{search_query}%')).all()
    else:
        people = Person.query.all()

    if sort_by == 'expiry':
        people = sorted(people, key=lambda p: p.checks[-1].get_expiry_date() if p.checks else datetime.max)
    elif sort_by == 'fio':
        people = sorted(people, key=lambda p: p.fio)
    elif sort_by == 'number':
        people = sorted(people, key=lambda p: p.number)

    current_date = datetime.now()
    return render_template('index.html', people=people, current_date=current_date, search_query=search_query,
                           check_sequence=check_sequence)


@app.route('/add', methods=['GET', 'POST'])
def add_person():
    if request.method == 'POST':
        fio = request.form['fio']
        birth_date = datetime.strptime(request.form['birth_date'], '%Y-%m-%d') if request.form['birth_date'] else None
        check_date = datetime.strptime(request.form['check_date'], '%Y-%m-%d')
        check_type = request.form['check_type']
        status = request.form['status']
        diagnosis = request.form['diagnosis']
        photo = request.files.get('photo')

        photo_path = None
        if photo and photo.filename:
            filename = photo.filename
            photo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            photo.save(photo_path)

        person = Person(number=Person.next_number, fio=fio, birth_date=birth_date)
        Person.next_number += 1
        db.session.add(person)
        db.session.commit()

        new_check = MedicalCheck(person_id=person.id, check_date=check_date, check_type=check_type,
                                 status=status, diagnosis=diagnosis, photo_path=photo_path)
        db.session.add(new_check)
        db.session.commit()
        flash('Персонал добавлен')
        return redirect(url_for('index'))
    return render_template('add.html')


@app.route('/edit/<int:person_id>', methods=['GET', 'POST'])
def edit_person(person_id):
    person = Person.query.get_or_404(person_id)
    if request.method == 'POST':
        if 'add_check' in request.form:
            check_date = datetime.strptime(request.form['check_date'], '%Y-%m-%d')
            check_type = request.form['check_type']
            status = request.form['status']
            diagnosis = request.form['diagnosis']
            photo = request.files.get('photo')

            photo_path = None
            if photo and photo.filename:
                filename = photo.filename
                photo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                photo.save(photo_path)

            new_check = MedicalCheck(person_id=person.id, check_date=check_date, check_type=check_type,
                                     status=status, diagnosis=diagnosis, photo_path=photo_path)
            db.session.add(new_check)
            db.session.commit()
            flash('Осмотр добавлен')
        return redirect(url_for('edit_person', person_id=person_id))

    last_check = MedicalCheck.query.filter_by(person_id=person_id).order_by(MedicalCheck.check_date.desc()).first()
    next_check_type, next_check_date = ("vlek", datetime.now()) if not last_check else last_check.get_next_check()
    return render_template('edit.html', person=person, next_check_type=next_check_type, next_check_date=next_check_date)


@app.route('/delete/<int:person_id>')
def delete_person(person_id):
    person = Person.query.get_or_404(person_id)
    for check in person.checks:
        if check.photo_path and os.path.exists(check.photo_path):
            os.remove(check.photo_path)
        db.session.delete(check)
    db.session.delete(person)
    db.session.commit()
    flash('Персонал удален')
    return redirect(url_for('index'))


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)