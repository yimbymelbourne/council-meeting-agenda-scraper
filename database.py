import sqlite3
import datetime
import json

def init():
  conn = sqlite3.connect('agendas.db')
  c = conn.cursor()
  c. execute('''CREATE TABLE IF NOT EXISTS agendas
                (id INTEGER PRIMARY KEY, 
                date TEXT, 
                link TEXT, 
                council TEXT, 
                result BLOB)''')
  conn.commit()
  conn.close()
  
def insert(council: str, link: str, result: dict):
  date = datetime.datetime.now().strftime("%Y-%m-%d")
  binary_result = json.dumps(result).encode()
  conn = sqlite3.connect('agendas.db')
  c = conn.cursor()
  c.execute('INSERT INTO agendas (date, link, council, result) VALUES (?, ?, ?, ?)', 
            (date, link, council, binary_result))
  conn.commit()
  conn.close()

def check_link(link: str):
  conn = sqlite3.connect('agendas.db')
  c = conn.cursor()
  c.execute('SELECT * FROM agendas WHERE link=?', (link,))
  result = c.fetchone()
  conn.close()
  return result