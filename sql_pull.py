import pyodbc

try:
    conn = pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        "SERVER=192.168.0.208,1433;"
        "DATABASE=Therapy-new;"
        "UID=dev;"
        "PWD=Lkopmn#123;"
         'TrustServerCertificate=yes;Encrypt=yes;'
    )

    cursor = conn.cursor()
    cursor.execute("SELECT TOP 10 * FROM dbo.Therapy_Details")  # example query

    for row in cursor.fetchall():
        print(row)

    conn.close()

except Exception as e:
    print("❌ Error:", e)
