import pyodbc

conn = pyodbc.connect(
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=192.168.0.208,1433;"
    "DATABASE=Therapy-new;"
    "UID=dev;"
    "PWD=Lkopmn#123;"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)
print("✅ Connected successfully!")
