import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app import create_app

app = create_app()

with app.app_context():
    print("CHUỖI KẾT NỐI DATABASE THỰC TẾ:")
    print(app.config['SQLALCHEMY_DATABASE_URI'])