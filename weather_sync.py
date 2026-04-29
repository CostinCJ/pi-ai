import json as _json
import requests
from config import OWM_API_KEY as API_KEY

CITY = 'Cluj-Napoca,RO'
_PRECIP_KEYWORDS = {'rain', 'snow', 'drizzle', 'storm', 'sleet', 'hail'}


def get_current_weather():
    """Fetches current weather and returns a plain-text summary for the AI."""
    url = f"http://api.openweathermap.org/data/2.5/weather?q={CITY}&appid={API_KEY}&units=metric"
    
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if response.status_code == 200:
            temp = data['main']['temp']
            desc = data['weather'][0]['description']
            humidity = data['main']['humidity']
            
            summary = f"The current weather in Cluj-Napoca is {temp:.1f}°C with {desc}. Humidity is at {humidity}%."
            print(summary)
            return summary
        else:
            print(f"Error {response.status_code}: {data.get('message', 'Unknown error')}")
            return "Weather data unavailable."
            
    except Exception as e:
        print(f"Failed to fetch weather: {e}")
        return "Weather data unavailable."

def get_weather_change():
    url = f"http://api.openweathermap.org/data/2.5/weather?q={CITY}&appid={API_KEY}&units=metric"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return None
        data = response.json()
        temp = round(data['main']['temp'], 1)
        desc = data['weather'][0]['description']
        today = {"temp": temp, "desc": desc}

        import db_helpers
        yesterday_raw = db_helpers.get_proactive_state('yesterday_weather')
        db_helpers.set_proactive_state('yesterday_weather', _json.dumps(today))

        if not yesterday_raw:
            return None
        yesterday = _json.loads(yesterday_raw)

        delta_temp = abs(temp - yesterday['temp'])
        old_precip = any(k in yesterday['desc'] for k in _PRECIP_KEYWORDS)
        new_precip = any(k in desc for k in _PRECIP_KEYWORDS)

        if delta_temp > 8 or (old_precip != new_precip):
            return {
                "delta_temp": delta_temp,
                "old_desc": yesterday['desc'],
                "new_desc": desc,
                "summary": f"weather changed: {yesterday['desc']} → {desc}, was {yesterday['temp']}°C now {temp}°C"
            }
        return None
    except Exception:
        return None


if __name__ == '__main__':
    get_current_weather()
