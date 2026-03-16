import time
import csv
from datetime import date
from typing import List, Dict, Optional
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class ChampionatGrabber:
    def __init__(self, chrome_path: str, chromedriver_path: str, headless: bool = False, timeout: int = 30):
        self.chrome_path = chrome_path
        self.chromedriver_path = chromedriver_path
        self.headless = headless
        self.timeout = timeout

    def _setup_driver(self):
        options = Options()
        options.binary_location = self.chrome_path
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_experimental_option("excludeSwitches", ["enable-logging"])
        if self.headless:
            options.add_argument("--headless=new")
        driver = webdriver.Chrome(service=Service(self.chromedriver_path), options=options)
        return driver

    def grab_day(self, date_str: str) -> List[Dict]:
        """Собираем матчи за одну дату, открывая новую вкладку для каждой даты"""
        driver = self._setup_driver()
        matches = []

        try:
            url = f"https://www.championat.com/stat/#{date_str}"
            driver.get(url)
            time.sleep(3)

            # Закрываем cookie
            selectors = [
                "#onetrust-accept-btn-handler",
                "button[aria-label*='Принять']",
                "button[aria-label*='accept']",
                ".cookie-accept",
                ".cookies__button",
                "button[data-gtm='consent.accept']",
                ".consent__button"
            ]
            for sel in selectors:
                try:
                    els = driver.find_elements(By.CSS_SELECTOR, sel)
                    for el in els:
                        if el.is_displayed():
                            el.click()
                            time.sleep(0.3)
                            break
                except Exception:
                    continue

            # Ждем загрузки матчей
            try:
                WebDriverWait(driver, self.timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".results-item"))
                )
            except Exception:
                return []

            # Скроллим до конца
            last_height = driver.execute_script("return document.body.scrollHeight")
            for _ in range(6):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(0.7)
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height

            # Сбор данных
            tournament_blocks = driver.find_elements(By.CSS_SELECTOR, ".mc-sport-tournament")
            for block in tournament_blocks:
                try:
                    tournament_name = ""
                    try:
                        tournament_name = block.find_element(By.CSS_SELECTOR, "a.title__link").text.strip()
                    except Exception:
                        pass

                    match_elements = block.find_elements(By.CSS_SELECTOR, ".results-item")
                    for el in match_elements:
                        try:
                            text_date = ""
                            try:
                                text_date = el.find_element(By.CSS_SELECTOR, ".results-item__title-date").text.strip()
                            except Exception:
                                text_date = date_str
                            match_time = text_date.split()[-1] if text_date else ""

                            participants = ""
                            try:
                                participants = el.find_element(By.CSS_SELECTOR, ".results-item__title-name").text.strip()
                            except Exception:
                                participants = ""

                            if participants:
                                match = {
                                    "tournament": tournament_name,
                                    "date": date_str,
                                    "time": match_time,
                                    "participants": participants
                                }
                                matches.append(match)
                        except Exception:
                            continue
                except Exception:
                    continue
        finally:
            driver.quit()

        return matches

    def grab_month(self, year: int, month: int, output_csv: str):
        """Собираем матч за весь месяц в один CSV"""
        from calendar import monthrange
        days = [date(year, month, d).isoformat() for d in range(1, monthrange(year, month)[1]+1)]

        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["tournament", "date", "time", "participants"])
            writer.writeheader()
            for day in days:
                print(f"Собираем матчи за {day}...")
                day_matches = self.grab_day(day)
                for m in day_matches:
                    writer.writerow(m)
                print(f"Найдено матчей: {len(day_matches)}")
        print(f"Месячный CSV сохранен в {output_csv}")


if __name__ == "__main__":
    grabber = ChampionatGrabber(
        chrome_path=r"chrome-win64\chrome.exe",
        chromedriver_path=r"chromedriver-win64\chromedriver.exe",
        headless=False
    )
    grabber.grab_month(2026, 2, "matches_february_2026.csv")
