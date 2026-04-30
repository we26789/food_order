from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-strong-secret-key-change-me'

# --------------------- 数据库配置（MySQL） ---------------------
# 请将下面的信息修改为你自己的 MySQL 连接参数
DB_USER = 'root'          # 数据库用户名
DB_PASS = '123456' # 数据库密码
DB_HOST = '127.0.0.1'     # 数据库主机，局域网内需改为服务器 IP
DB_PORT = '3306'          # 数据库端口
DB_NAME = 'family_menu'   # 数据库名（需提前创建好）

app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = '请先登录'

# --------------------- 数据模型 ---------------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'cooker' 或 'customer'

class Dish(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(200))
    image_url = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dish_id = db.Column(db.Integer, db.ForeignKey('dish.id'), nullable=False)
    dish = db.relationship('Dish', backref='orders')
    customer = db.Column(db.String(50), nullable=False)   # 顾客用户名
    quantity = db.Column(db.Integer, default=1)
    note = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# --------------------- Flask-Login 用户加载 ---------------------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --------------------- 权限装饰器 ---------------------
def role_required(role):
    """限制指定角色才能访问"""
    def decorator(func):
        @wraps(func)
        @login_required
        def wrapper(*args, **kwargs):
            if current_user.role != role:
                flash('权限不足', 'danger')
                if current_user.role == 'cooker':
                    return redirect(url_for('orders'))
                else:
                    return redirect(url_for('index'))
            return func(*args, **kwargs)
        return wrapper
    return decorator

# --------------------- 初始化数据库 & 默认用户 ---------------------
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='Cooker').first():
        db.session.add(User(
            username='Cooker',
            password_hash=generate_password_hash('123456'),
            role='cooker'
        ))
    if not User.query.filter_by(username='Customer').first():
        db.session.add(User(
            username='Customer',
            password_hash=generate_password_hash('123456'),
            role='customer'
        ))
    db.session.commit()

# --------------------- 登录/登出/改密 ---------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash(f'欢迎，{user.username}！', 'success')
            # 按角色跳转
            if user.role == 'cooker':
                return redirect(url_for('orders'))
            else:
                return redirect(url_for('index'))
        flash('用户名或密码错误', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已退出登录', 'info')
    return redirect(url_for('login'))

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        old_pw = request.form.get('old_password', '')
        new_pw = request.form.get('new_password', '')
        confirm_pw = request.form.get('confirm_password', '')
        if not check_password_hash(current_user.password_hash, old_pw):
            flash('原密码错误', 'danger')
        elif len(new_pw) < 6:
            flash('新密码至少6位', 'warning')
        elif new_pw != confirm_pw:
            flash('两次新密码不一致', 'danger')
        else:
            current_user.password_hash = generate_password_hash(new_pw)
            db.session.commit()
            flash('密码修改成功，请重新登录', 'success')
            logout_user()
            return redirect(url_for('login'))
    return render_template('change_password.html')

# --------------------- 顾客：点菜页面 ---------------------
@app.route('/', methods=['GET', 'POST'])
@role_required('customer')
def index():
    if request.method == 'POST':
        # 自动使用当前登录顾客的用户名
        customer_name = current_user.username
        dish_id = request.form.get('dish_id')
        quantity = request.form.get('quantity', 1, type=int)
        note = request.form.get('note', '').strip()
        dish = Dish.query.get(dish_id)
        if not dish:
            flash('菜品不存在', 'danger')
            return redirect(url_for('index'))
        order = OrderItem(
            dish_id=dish.id,
            customer=customer_name,
            quantity=quantity,
            note=note
        )
        db.session.add(order)
        db.session.commit()
        flash(f'成功下单：{dish.name} x {quantity}', 'success')
        return redirect(url_for('index'))
    dishes = Dish.query.order_by(Dish.created_at.desc()).all()
    return render_template('index.html', dishes=dishes)

# --------------------- 厨师：订单汇总 ---------------------
@app.route('/orders')
@role_required('cooker')
def orders():
    order_list = OrderItem.query.order_by(OrderItem.created_at.desc()).all()
    return render_template('orders.html', orders=order_list)

# --------------------- 厨师：菜品管理 ---------------------
@app.route('/admin', methods=['GET', 'POST'])
@role_required('cooker')
def admin():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            image_url = request.form.get('image_url', '').strip()
            if not name:
                flash('菜品名称不能为空', 'danger')
                return redirect(url_for('admin'))
            dish = Dish(name=name, description=description, image_url=image_url)
            db.session.add(dish)
            db.session.commit()
            flash(f'菜品 "{name}" 添加成功', 'success')
        elif action == 'delete':
            dish_id = request.form.get('dish_id', type=int)
            dish = Dish.query.get(dish_id)
            if dish:
                OrderItem.query.filter_by(dish_id=dish.id).delete()
                db.session.delete(dish)
                db.session.commit()
                flash(f'菜品 "{dish.name}" 及关联订单已删除', 'info')
        elif action == 'clear_orders':
            num = OrderItem.query.delete()
            db.session.commit()
            flash(f'已清空所有订单（共 {num} 条）', 'info')
        return redirect(url_for('admin'))
    dishes = Dish.query.order_by(Dish.created_at.desc()).all()
    return render_template('admin.html', dishes=dishes)

# --------------------- 启动 ---------------------
if __name__ == '__main__':
    print("=" * 40)
    print("家庭点菜系统启动中...")
    print("厨师账号：Cooker   密码：123456")
    print("顾客账号：Customer 密码：123456")
    print("局域网访问：http://本机IP:5000")
    print("=" * 40)
    app.run(debug=True, host='0.0.0.0', port=5000)