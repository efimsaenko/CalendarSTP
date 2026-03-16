import os
import re
import csv
import json
import urllib.request
from typing import List, Dict, Optional

from logger import get_logger
logger = get_logger("grabber")


class ChampionatGrabber:
    def __init__(
        self,
        chrome_path: str = "",
        chromedriver_path: str = "",
        headless: bool = False,
        timeout: int = 30,
    ):
        """
        chrome_path / chromedriver_path / headless сохранены для обратной совместимости,
        но больше не используются — браузер не нужен.
        timeout: таймаут HTTP-запроса (секунд).
        """
        self.chrome_path = chrome_path
        self.chromedriver_path = chromedriver_path
        self.headless = headless
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Внутренние helpers
    # ------------------------------------------------------------------

    def _fetch_json(self, date_str: str, request_id: Optional[str] = None) -> dict:
        url = f"https://www.championat.com/stat/data/{date_str}"
        logger.info(f"Fetching {url}", extra={"request_id": request_id})
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, */*",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8")
        return json.loads(raw)

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Приводит имена участников к единому виду «A – B»."""
        name = re.sub(r"\s*(–|—|\n)\s*", " – ", name)
        return " ".join(name.split())

    @staticmethod
    def _build_save_dir(base_dir: str, date_str: str) -> str:
        """Строит путь base_dir/YYYY/MM/ из даты 'YYYY-MM-DD'."""
        parts = date_str.split("-")
        year = parts[0] if len(parts) > 0 else "unknown"
        month = parts[1] if len(parts) > 1 else "unknown"
        return os.path.join(base_dir, year, month)

    # ------------------------------------------------------------------
    # Публичный API (семантика не изменена)
    # ------------------------------------------------------------------

    def grab(
        self,
        date_str: str,
        save_csv: bool = True,
        save_dir: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        Собирает матчи за конкретную дату.

        date_str  : 'YYYY-MM-DD'
        save_csv  : если True, сохраняет CSV в save_dir/YYYY/MM/.
        save_dir  : корневая папка (если None — ./data/ рядом с модулем).
        request_id: для логов.

        Возвращает список словарей с ключами:
            tournament, date, time, participants, stage
        """
        try:
            data = self._fetch_json(date_str, request_id=request_id)
        except Exception as exc:
            logger.error(f"Failed to fetch data: {exc}", extra={"request_id": request_id})
            return []

        matches: List[Dict] = []

        sports: dict = data.get("matches", {})
        for sport_key, sport_data in sports.items():
            if not isinstance(sport_data, dict):
                continue
            tournaments: dict = sport_data.get("tournaments", {})
            for t_key, t_data in tournaments.items():
                if not isinstance(t_data, dict):
                    continue

                tournament_name: str = t_data.get("name", "")
                raw_matches: list = t_data.get("matches", [])

                for m in raw_matches:
                    if not isinstance(m, dict):
                        continue
                    try:
                        match_date: str = m.get("date", date_str)
                        match_time: str = m.get("time", "")

                        # Участники — берём из поля name матча
                        participants = self._normalize_name(m.get("name", ""))

                        # stage — group.stage ("group", "playoff", "preliminary", ...)
                        group: dict = m.get("group", {})
                        stage: str = group.get("stage", "") if isinstance(group, dict) else ""

                        record = {
                            "tournament": tournament_name,
                            "date": match_date,
                            "time": match_time,
                            "participants": participants,
                            "stage": stage,
                        }
                        matches.append(record)

                        if save_csv:
                            base_dir = save_dir or os.path.join(
                                os.path.dirname(os.path.abspath(__file__)), "data"
                            )
                            out_dir = self._build_save_dir(base_dir, match_date)
                            os.makedirs(out_dir, exist_ok=True)
                            file_path = os.path.join(out_dir, f"matches_{date_str}.csv")

                            fieldnames = ["tournament", "date", "time", "participants", "stage"]
                            write_header = (
                                not os.path.exists(file_path)
                                or os.path.getsize(file_path) == 0
                            )
                            with open(file_path, "a", newline="", encoding="utf-8") as f:
                                writer = csv.DictWriter(f, fieldnames=fieldnames)
                                if write_header:
                                    writer.writeheader()
                                writer.writerow(record)

                    except Exception:
                        continue

        logger.info(
            f"Collected {len(matches)} matches for {date_str}",
            extra={"request_id": request_id},
        )
        return matches

    def close(self):
        """Оставлен для обратной совместимости. Ничего не делает."""
        pass


# ---------------------------------------------------------------------------
# Smoke-test при прямом запуске
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    grabber = ChampionatGrabber(headless=True)
    try:
        m = grabber.grab("2026-03-14", save_csv=True, request_id="localtest")
        print("collected", len(m))
        if m:
            import pprint
            pprint.pprint(m[:3])
    finally:
        grabber.close()