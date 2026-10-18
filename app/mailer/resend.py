import time
from typing import List, Optional

import requests

from app.mailer.base import Mailer, Message, SendResult, clean_header

API = "https://api.resend.com"
BATCH_SIZE = 100
MAX_ATTEMPTS = 4


class ResendMailer(Mailer):
    name = "resend"

    def configuration_error(self) -> Optional[str]:
        if not self.config.resend_api_key:
            return "Resend API key is not set."
        if not self.config.sender:
            return "Sender address is not set. It must use a domain verified in Resend."
        return None

    def _payload(self, message: Message) -> dict:
        payload = {
            "from": clean_header(self.config.sender),
            "to": [clean_header(message.to)],
            "subject": clean_header(message.subject),
            "text": message.text,
        }
        if message.html:
            payload["html"] = message.html
        return payload

    def _post(self, path: str, body) -> requests.Response:
        headers = {
            "Authorization": f"Bearer {self.config.resend_api_key}",
            "Content-Type": "application/json",
            "User-Agent": "votilio/3",
        }
        response = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = requests.post(API + path, json=body, headers=headers, timeout=(5, 25))
            except requests.RequestException as exc:
                if attempt == MAX_ATTEMPTS - 1:
                    raise
                time.sleep(0.5 * (attempt + 1))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < MAX_ATTEMPTS - 1:
                    try:
                        wait = float(response.headers.get("retry-after", 0.6 * (attempt + 1)))
                    except ValueError:
                        wait = 1.0
                    time.sleep(min(wait, 5.0))
                    continue
            return response
        return response

    @staticmethod
    def _error(response: requests.Response) -> str:
        try:
            data = response.json()
            detail = data.get("message") or data.get("error") or response.text
        except ValueError:
            detail = response.text
        return f"Resend {response.status_code}: {str(detail)[:300]}"

    def _send_one(self, message: Message) -> SendResult:
        try:
            response = self._post("/emails", self._payload(message))
        except requests.RequestException as exc:
            return SendResult(False, f"Could not reach Resend: {exc}")
        if response.status_code == 200:
            return SendResult(True, provider_id=(response.json() or {}).get("id"))
        return SendResult(False, self._error(response))

    def send_many(self, messages: List[Message]) -> List[SendResult]:
        error = self.configuration_error()
        if error:
            return [SendResult(False, error) for _ in messages]
        if len(messages) == 1:
            return [self._send_one(messages[0])]
        results: List[SendResult] = []
        for start in range(0, len(messages), BATCH_SIZE):
            chunk = messages[start:start + BATCH_SIZE]
            try:
                response = self._post("/emails/batch", [self._payload(m) for m in chunk])
            except requests.RequestException as exc:
                results.extend(SendResult(False, f"Could not reach Resend: {exc}") for _ in chunk)
                continue
            if response.status_code == 200:
                ids = (response.json() or {}).get("data") or []
                for i, _ in enumerate(chunk):
                    pid = ids[i].get("id") if i < len(ids) and isinstance(ids[i], dict) else None
                    results.append(SendResult(True, provider_id=pid))
            elif response.status_code in (400, 401, 403):
                results.extend(SendResult(False, self._error(response)) for _ in chunk)
            else:
                # One bad address fails a whole batch; resend individually to isolate it.
                results.extend(self._send_one(m) for m in chunk)
        return results
