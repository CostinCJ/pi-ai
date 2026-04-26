import requests
from config import OWM_API_KEY as API_KEY

CITY = 'Cluj-Napoca,RO'

def get_current_weather():
    """Fetches current weather and returns a plain-text summary for the AI."""
    url = f"http://api.openweathermap.org/data/2.5/weather?q={CITY}&appid={API_KEY}&units=metric"
    
    try:
        response = requests.get(url)
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
            return None
            
    except Exception as e:
        print(f"Failed to fetch weather: {e}")
        return None

if __name__ == '__main__':
    get_current_weather()

