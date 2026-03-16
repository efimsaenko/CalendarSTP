import shutil, os

import CONTENT

src = r"C:\Users\efim\PycharmProjects\CallendarJoger\MonthCalendarExcel.py"
bak = src + ".bak"

# Бэкап старого
shutil.copy(src, bak)
print(f"Бэкап: {bak}")

# Записываем правильный файл
with open(src, "w", encoding="utf-8") as f:
    f.write(CONTENT)

print("Готово. Проверяем...")
from importlib import import_module
import sys
if "MonthCalendarExcel" in sys.modules:
    del sys.modules["MonthCalendarExcel"]

m = import_module("MonthCalendarExcel")
print("Функции:", [x for x in dir(m) if not x.startswith("_")])