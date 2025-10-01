# app.py
import os
from flask import Flask, render_template_string, request
import folium
from folium.plugins import MarkerCluster
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import traceback

# Optional CSV support (if you upload a hospitals.csv with real data)
try:
    import pandas as pd
except Exception:
    pd = None

app = Flask(__name__)

# --- Load hospitals dataset if hospitals.csv exists; otherwise use sample data ---
def load_hospitals():
    csv_path = "hospitals.csv"
    if pd and os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        # Expect columns: name,type,latitude,longitude,doctors (pipe-separated),rating
        hospitals = []
        for _, r in df.iterrows():
            hospitals.append({
                "name": str(r.get("name","")).strip(),
                "type": str(r.get("type","")).strip(),
                "coords": (float(r.get("latitude")), float(r.get("longitude"))),
                "doctors": [d.strip() for d in str(r.get("doctors","")).split("|") if d.strip()],
                "rating": float(r.get("rating") if not pd.isna(r.get("rating")) else 0)
            })
        return hospitals
    # fallback sample data (can be replaced with a full CSV)
    return [
        {"name":"AIIMS Delhi","type":"Multispeciality","coords":(28.5672,77.2100),"doctors":["Dr. Sharma","Dr. Rao"],"rating":4.8},
        {"name":"Apollo Hospital Chennai","type":"Multispeciality","coords":(13.0500,80.2500),"doctors":["Dr. Kumar","Dr. Meena"],"rating":4.5},
        {"name":"NIMHANS Bangalore","type":"Psychiatry","coords":(12.9780,77.5910),"doctors":["Dr. Ramesh"],"rating":4.6},
        {"name":"KEM Hospital Mumbai","type":"General","coords":(18.9875,72.8260),"doctors":["Dr. Patil"],"rating":4.4},
        {"name":"Vinayaka Mission Hospital Karaikal","type":"Multispeciality","coords":(10.9094,79.8461),"doctors":["Dr. R.T. Kannapiran"],"rating":4.3},
    ]

HOSPITALS = load_hospitals()

# --- HTML template (Bootstrap) embedded in Python ---
TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Hospital Finder (India)</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.1/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background:#f8f9fa; }
    .map-card iframe { width:100%; height:650px; border:none; }
    .small-muted { font-size:0.9rem; color:#6c757d; }
  </style>
</head>
<body>
<div class="container py-4">
  <h1 class="text-center mb-3">India Hospital Finder</h1>

  <div class="card shadow-sm mb-4">
    <div class="card-body">
      <form method="POST" class="row g-2">
        <div class="col-md-7">
          <input name="location" placeholder="City, locality or landmark (e.g. 'Karaikal Bazaar' or 'Chennai')" class="form-control" value="{{ request_form.location or '' }}" required>
        </div>
        <div class="col-md-3">
          <select name="type" class="form-select">
            {% for t in types %}
              <option {% if request_form.type==t %}selected{% endif %}>{{ t }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-md-2 d-grid">
          <button class="btn btn-primary">Search</button>
        </div>
      </form>
      <div class="mt-2 small-muted">Geocoding by OpenStreetMap Nominatim (free). For production use, consider Mapbox or Google Maps geocoding API for stability and quotas.</div>
    </div>
  </div>

  {% if error %}
    <div class="alert alert-danger">{{ error }}</div>
  {% endif %}

  {% if best %}
    <div class="row mb-3">
      <div class="col-md-8">
        <div class="card map-card shadow-sm">
          {{ map_html|safe }}
        </div>
      </div>
      <div class="col-md-4">
        <div class="card shadow-sm p-3">
          <h5 class="mb-2">🌟 Best Hospital Nearby</h5>
          <p class="mb-1"><strong>{{ best.name }}</strong></p>
          <p class="small-muted mb-1">{{ best.type }} • Rating: {{ '%.1f'|format(best.rating) }} ★</p>
          <p class="mb-1">Distance: {{ '%.2f'|format(best.distance) }} km</p>
          <p class="mb-1">Doctors:</p>
          <ul>
            {% for doc in best.doctors %}
              <li>{{ doc }}</li>
            {% endfor %}
          </ul>
        </div>

        {% if results %}
        <div class="card mt-3 shadow-sm p-3">
          <h6>Other nearby hospitals</h6>
          <ol>
            {% for h in results %}
              <li><strong>{{ h.name }}</strong><br><small class="small-muted">{{ h.type }} • {{ '%.2f'|format(h.distance) }} km • {{ '%.1f'|format(h.rating) }}★</small></li>
            {% endfor %}
          </ol>
        </div>
        {% endif %}
      </div>
    </div>
  {% endif %}

  <footer class="text-center small-muted mt-4">Data: sample unless you upload a real <code>hospitals.csv</code> (name,type,latitude,longitude,doctors|pipe|separated,rating). Nominatim usage policies apply.</footer>
</div>
</body>
</html>
"""

# --- Utilities ---
def geocode_location(text):
    geolocator = Nominatim(user_agent="india_hospital_finder", timeout=10)
    # try raw input first, then "..., India"
    loc = geolocator.geocode(text)
    if not loc:
        loc = geolocator.geocode(f"{text}, India")
    return loc

@app.route("/", methods=["GET", "POST"])
def index():
    error = None
    map_html = None
    best = None
    results = []
    types = sorted(list({h["type"] for h in HOSPITALS}) | {"All"})
    request_form = {"location": "", "type": "All"}
    try:
        if request.method == "POST":
            request_form["location"] = request.form.get("location","").strip()
            request_form["type"] = request.form.get("type","All")

            if not request_form["location"]:
                error = "Please enter a location."
            else:
                loc = geocode_location(request_form["location"])
                if not loc:
                    error = "Location not found. Try a different query or be more specific."
                else:
                    user_coords = (loc.latitude, loc.longitude)

                    # filter by type
                    filtered = [dict(h) for h in HOSPITALS if request_form["type"] == "All" or h["type"] == request_form["type"]]

                    # compute distances
                    for h in filtered:
                        h["distance"] = geodesic(user_coords, h["coords"]).km

                    if not filtered:
                        error = "No hospitals of that type are available in this dataset."
                    else:
                        # sort by distance
                        filtered.sort(key=lambda x: x["distance"])
                        # create folium map centered on user
                        m = folium.Map(location=user_coords, zoom_start=12, control_scale=True)
                        folium.Marker(user_coords, popup="Your location", icon=folium.Icon(color="red", icon="user")).add_to(m)

                        cluster = MarkerCluster()
                        cluster.add_to(m)
                        for h in filtered:
                            popup = f"<b>{h['name']}</b><br>{h['type']}<br>Rating: {h.get('rating',0)}★<br>Distance: {h['distance']:.2f} km<br>Doctors: {', '.join(h.get('doctors',[]))}"
                            folium.Marker(h["coords"], popup=popup, icon=folium.Icon(color="blue", icon="plus")).add_to(cluster)

                        # pick best hospital by rating then distance
                        best_sorted = sorted(filtered, key=lambda x: (-x.get("rating",0), x["distance"]))
                        best = best_sorted[0]
                        # include a green star marker for best
                        folium.Marker(best["coords"], popup=f"Best: {best['name']}", icon=folium.Icon(color="green", icon="star")).add_to(m)

                        # produce HTML for map (embed)
                        map_html = m._repr_html_()

                        # return top 8 results
                        results = filtered[:8]
    except Exception as e:
        error = "Server error: " + str(e)
        # log stack trace to server logs
        print(traceback.format_exc())

    return render_template_string(TEMPLATE,
                                  error=error,
                                  map_html=map_html,
                                  best=best,
                                  results=results,
                                  types=types,
                                  request_form=request_form)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # In production you should set debug=False
    app.run(host="0.0.0.0", port=port, debug=False)
