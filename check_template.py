with open(r'templates\masters\item_master_manage.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()
    for i in range(59, 67):  # Lines 60-67 (0-indexed)
        print(f"{i+1}: {lines[i]}", end='')
