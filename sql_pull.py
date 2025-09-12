import pyodbc

try:
    conn = pyodbc.connect(
        "DRIVER={SQL Server};"
        "SERVER=192.168.0.208,1433;"
        "DATABASE=OPTherapy;"
        "UID=dev;"
        "PWD=Lkopmn#123;"
    )

    cursor = conn.cursor()
    cursor.execute("SELECT TOP 10 * FROM dbo.Booking")  # example query

    for row in cursor.fetchall():
        print(row)

    conn.close()

except Exception as e:
    print("❌ Error:", e)
