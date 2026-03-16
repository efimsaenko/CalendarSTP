# ChampionatGrabber.py
import os
import re
import time
import csv
from typing import List, Dict, Optional
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from logger import get_logger
logger = get_logger("grabber")

class ChampionatGrabber:
    def __init__(self, chrome_path: str, chromedriver_path: str, headless: bool = False, timeout: int = 30):
        """
        chrome_path: путь к chrome.exe
        chromedriver_path: путь к chromedriver.exe
        headless: запускать в фоне
        timeout: таймаут ожиданий (секунд)
        """
        self.chrome_path = chrome_path
        self.chromedriver_path = chromedriver_path
        self.headless = headless
        self.timeout = timeout
        self.driver: Optional[webdriver.Chrome] = None

    def _setup_driver(self, request_id: Optional[str] = None):
        options = Options()
        if self.chrome_path:
            options.binary_location = self.chrome_path
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_experimental_option("excludeSwitches", ["enable-logging"])
        # stable headless flag
        if self.headless:
            options.add_argument("--headless")
            options.add_argument("--window-size=1920,1080")
        logger.info("Launching ChromeDriver", extra={"request_id": request_id})
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
                        try:
                            el.click()
                            time.sleep(0.3)
                            return
                        except Exception:
                            continue
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

    def grab(self, date_str: str, save_csv: bool = True, save_dir: Optional[str] = None, request_id: Optional[str] = None) -> List[Dict]:
        """
        Собирает матчи за конкретную дату.
        date_str: 'YYYY-MM-DD'
        save_csv: если True, сохраняет CSV в save_dir.
        save_dir: путь к папке, куда сохранять (если None и save_csv True -> use current dir)
        request_id: для логов
        """
        if not self.driver:
            self._setup_driver(request_id=request_id)

        url = f"https://www.championat.com/stat/#{date_str}"
        logger.info(f"Chrome navigating to {url}", extra={"request_id": request_id})
        self.driver.get(url)
        time.sleep(2)  # небольшая пауза на подгрузку
        self._try_close_cookie()
        self._scroll_to_bottom_slow(attempts=6, pause=0.6)

        try:
            WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".results-item"))
            )
        except Exception:
            # если не загрузилось, пробуем ещё
            self._scroll_to_bottom_slow(attempts=6, pause=0.6)
            try:
                WebDriverWait(self.driver, self.timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".results-item"))
                )
            except Exception:
                logger.warning("No results items found after wait", extra={"request_id": request_id})
                return []

        matches: List[Dict] = []
        tournament_blocks = self.driver.find_elements(By.CSS_SELECTOR, ".mc-sport-tournament")
        for block in tournament_blocks:
            try:
                tournament_name = ""
                try:
                    tournament_name = block.find_element(By.CSS_SELECTOR, "a.title__link").text.strip()
                except Exception:
                    tournament_name = ""
                match_elements = block.find_elements(By.CSS_SELECTOR, ".results-item")
                for el in match_elements:
                    try:
                        text_date = ""
                        try:
                            text_date = el.find_element(By.CSS_SELECTOR, ".results-item__title-date").text.strip()
                        except Exception:
                            text_date = date_str

                        # Извлекаем только время (последний фрагмент)
                        match_time = ""
                        parts = text_date.split()
                        if len(parts) >= 1:
                            match_time = parts[-1]

                        participants = ""
                        try:
                            participants = el.find_element(By.CSS_SELECTOR, ".results-item__title-name").text
                            participants = re.sub(r"\s*(–|—|\n)\s*", " – ", participants)
                            participants = " ".join(participants.split())
                        except Exception:
                            participants = ""

                        match = {
                            "tournament": tournament_name,
                            "date": date_str,
                            "time": match_time,
                            "participants": participants
                        }
                        matches.append(match)

                        if save_csv:
                            # write to provided save_dir or to current file location
                            base_dir = save_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
                            os.makedirs(base_dir, exist_ok=True)
                            filedPath = os.path.join(base_dir, f"matches_{date_str}.csv")
                            with open(filedPath, "a", newline="", encoding="utf-8") as f:
                                writer = csv.DictWriter(f, fieldnames=["tournament", "date", "time", "participants"])
                                if f.tell() == 0:
                                    writer.writeheader()
                                writer.writerow(match)
                    except Exception:
                        # per-match errors should not stop parsing
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


# If run directly, basic smoke test (not intended for production)
if __name__ == "__main__":
    grabber = ChampionatGrabber(
        chrome_path=r"chrome-win64\chrome.exe",
        chromedriver_path=r"chromedriver-win64\chromedriver.exe",
        headless=True
    )
    try:
        m = grabber.grab("2026-03-01", save_csv=True, request_id="localtest")
        print("collected", len(m))
    finally:
        grabber.close()