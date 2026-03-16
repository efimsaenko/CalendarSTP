from MonthGrabbScheduler import MonthGrabbScheduler

def run():
    scheduler = MonthGrabbScheduler(
        chrome_path=r"chrome-win64\chrome.exe",
        chromedriver_path=r"chromedriver-win64\chromedriver.exe"
    )

    scheduler.run_month(year=2026, month=5,force_grab=True)
    #scheduler.grab_one_day("2026-03-31")

if __name__ == "__main__":
    run()