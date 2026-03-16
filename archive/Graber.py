import time
import csv
from typing import List, Dict, Optional
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class ChampionatGrabber:
    def __init__(self, chrome_path: str, chromedriver_path: str, headless: bool = False, timeout: int = 30):
        """
        chrome_path: путь к chrome.exe (портативный Chrome)
        chromedriver_path: путь к chromedriver.exe (совместимый с этим Chrome)
        headless: запускать в фоне
        timeout: таймаут ожиданий (секунд)
        """
        self.chrome_path = chrome_path
        self.chromedriver_path = chromedriver_path
        self.headless = headless
        self.timeout = timeout
        self.driver: Optional[webdriver.Chrome] = None

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
        self.driver = webdriver.Chrome(service=Service(self.chromedriver_path), options=options)

    def _try_close_cookie(self):
        """Закрываем возможные cookie-попапы"""
        if not self.driver:
            return
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
                els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    if el.is_displayed():
                        el.click()
                        time.sleep(0.3)
                        return
            except Exception:
                continue

    def _scroll_to_bottom_slow(self, attempts: int = 5, pause: float = 0.6):
        """Медленная прокрутка страницы для ленивой подгрузки"""
        if not self.driver:
            return
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        for _ in range(attempts):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(pause)
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

    def grab(self, date_str: str, save_csv: bool = True) -> List[Dict]:
        """
        Собирает матчи за конкретную дату.
        date_str: 'YYYY-MM-DD'
        save_csv: если True, сохраняет CSV по ходу
        """
        if not self.driver:
            self._setup_driver()

        url = f"https://www.championat.com/stat/#{date_str}"
        self.driver.get(url)
        time.sleep(3)  # время на подгрузку
        self._try_close_cookie()
        self._scroll_to_bottom_slow(attempts=6, pause=0.7)

        try:
            WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".results-item"))
            )
        except Exception:
            # если не загрузилось, повторная прокрутка
            self._scroll_to_bottom_slow(attempts=6, pause=0.7)
            try:
                WebDriverWait(self.driver, self.timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".results-item"))
                )
            except Exception:
                return []

        matches = []
        tournament_blocks = self.driver.find_elements(By.CSS_SELECTOR, ".mc-sport-tournament")
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
                        # Дата и время вместе на сайте
                        text_date = ""
                        try:
                            text_date = el.find_element(By.CSS_SELECTOR, ".results-item__title-date").text.strip()
                        except Exception:
                            text_date = date_str

                        # Извлекаем только время
                        match_time = ""
                        parts = text_date.split()
                        if len(parts) == 2:
                            match_time = parts[1]
                        elif len(parts) == 1:
                            match_time = parts[0]

                        # Названия участников
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

                            if save_csv:
                                with open(f"matches_{date_str}.csv", "a", newline="", encoding="utf-8") as f:
                                    writer = csv.DictWriter(f, fieldnames=["tournament", "date", "time", "participants"])
                                    if f.tell() == 0:
                                        writer.writeheader()
                                    writer.writerow(match)
                    except Exception:
                        continue
            except Exception:
                continue

        return matches

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None


# Пример использования
if __name__ == "__main__":
    grabber = ChampionatGrabber(
        chrome_path=r"chrome-win64\chrome.exe",
        chromedriver_path=r"chromedriver-win64\chromedriver.exe",
        headless=False
    )
    try:
        matches = grabber.grab("2025-11-01")
        print(f"Собрано матчей: {len(matches)}")
        for m in matches:
            print(m)
    finally:
        grabber.close()
