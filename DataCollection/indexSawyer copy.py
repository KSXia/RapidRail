import requests
import networkx as nx
import plotly.graph_objects as go
import plotly.io as pio
from collections import defaultdict
import json
import random

pio.renderers.default = "browser"

API_KEY = 'REDACTED'
HEADERS = {'api_key': API_KEY}

# 1. Get all stations
stations_url = "https://api.wmata.com/Rail.svc/json/jStations"
station_data = requests.get(stations_url, headers=HEADERS).json()["Stations"]

# 2. Merge multi-code stations
station_map = {}
coord_map = {}
merged_stations = {}

for s in station_data:
    name = s["Name"]
    code = s["Code"]
    lat, lon = s["Lat"], s["Lon"]
    alt_code = s["StationTogether1"]

    if alt_code:
        alt_station = next((x for x in station_data if x["Code"] == alt_code), None)
        if alt_station:
            name = alt_station["Name"]
    
    if name not in merged_stations:
        merged_stations[name] = {"codes": [], "lat": lat, "lon": lon}
    merged_stations[name]["codes"].append(code)

    station_map[code] = name
    coord_map[name] = (lat, lon)

# 3. Load line order from fixed file
with open("line_station_order.json", "r") as f:
    line_station_codes = json.load(f)

line_colors = {
    "RD": "#be1337",
    "BL": "#0076a8",
    "OR": "#f58220",
    "GR": "#00b140",
    "YL": "#f4c300",
    "SV": "#a2a4a1",
}

edges_by_line = defaultdict(set)
edges_lines_map = defaultdict(set)

for line, codes in line_station_codes.items():
    for i in range(len(codes) - 1):
        from_code = codes[i]
        to_code = codes[i + 1]
        from_name = station_map[from_code]
        to_name = station_map[to_code]
        edge = tuple(sorted((from_name, to_name)))
        edges_by_line[line].add(edge)
        edges_lines_map[edge].add(line)

# 4. Create the graph
G = nx.Graph()

for name, data in merged_stations.items():
    G.add_node(name, codes=data["codes"], pos=(data["lon"], data["lat"]))

# 5. Load transfer times
with open("transfer_times.json", "r") as f:
    transfer_times = json.load(f)

# Load custom (manual) connections like walkways or bus links
with open("custom_edges.json", "r") as f:
    custom_edges = json.load(f)

for station in G.nodes():
    G.nodes[station]["transfer_time"] = transfer_times.get(station, 0)

# 6. Add edges
for edge in edges_lines_map:
    G.add_edge(*edge)

# 7. Add rail time weights + wait time
print("🔄 Fetching travel time data...")
url = "https://api.wmata.com/Rail.svc/json/jSrcStationToDstStationInfo"
response = requests.get(url, headers=HEADERS).json()
travel_info = response["StationToStationInfos"]

rail_time_lookup = {}
for entry in travel_info:
    src = entry["SourceStation"]
    dst = entry["DestinationStation"]
    time = entry["RailTime"]
    key = tuple(sorted((src, dst)))
    rail_time_lookup[key] = time

for from_node, to_node in G.edges():
    from_codes = G.nodes[from_node]["codes"]
    to_codes = G.nodes[to_node]["codes"]

    min_time = None
    for src in from_codes:
        for dst in to_codes:
            key = tuple(sorted((src, dst)))
            if key in rail_time_lookup:
                min_time = rail_time_lookup[key]
                break
        if min_time is not None:
            break

    if min_time is not None:
        G[from_node][to_node]["weight"] = min_time + 1  # Add 1 min wait time
    else:
        print(f"⚠️ No travel time found between: {from_node} ↔ {to_node}")

for custom in custom_edges:
    u = custom["station1"]
    v = custom["station2"]
    weight = custom["time"]
    G.add_edge(u, v, weight=weight, custom_path=custom["pathName"])

# 8. Plotting
fig = go.Figure()

def format_time(minutes):
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours} hr {mins} min" if hours else f"{mins} min"


def animate_route(G, path):
    # Get station coordinates
    coords = [G.nodes[n]["pos"] for n in path]
    x_all, y_all = zip(*coords)
    
    # Create the background map (lines + stations)
    fig = go.Figure()

    # Plot background metro lines
    for edge in G.edges():
        u, v = edge
        x0, y0 = G.nodes[u]["pos"]
        x1, y1 = G.nodes[v]["pos"]
        fig.add_trace(go.Scatter(
            x=[x0, x1],
            y=[y0, y1],
            mode='lines',
            line=dict(width=2, color='lightgray'),
            hoverinfo='skip',
            showlegend=False
        ))

    # Plot all stations as background
    for n in G.nodes():
        x, y = G.nodes[n]['pos']
        fig.add_trace(go.Scatter(
            x=[x], y=[y],
            mode='markers',
            marker=dict(size=6, color='gray'),
            text=n,
            hoverinfo='text',
            showlegend=False
        ))

    # Animation frames: for each step, show the path so far and the current station
    frames = []
    for i in range(1, len(path)+1):
        # Growing path line
        frame_data = []
        if i > 1:
            frame_data.append(go.Scatter(
                x=x_all[:i], y=y_all[:i],
                mode='lines+markers',
                line=dict(width=4, color='blue'),
                marker=dict(size=10, color='blue'),
                name='Route so far',
                showlegend=False
            ))
        # Current station
        frame_data.append(go.Scatter(
            x=[x_all[i-1]], y=[y_all[i-1]],
            mode='markers+text',
            marker=dict(size=16, color='red'),
            text=[path[i-1]],
            textposition='top center',
            showlegend=False,
            name='Current Position'
        ))
        frames.append(go.Frame(data=frame_data, name=str(i-1)))
    
    # Add first frame traces (so the plot is initialized)
    initial_traces = []
    initial_traces.append(go.Scatter(
        x=[x_all[0]], y=[y_all[0]],
        mode='markers+text',
        marker=dict(size=16, color='red'),
        text=[path[0]],
        textposition='top center',
        showlegend=False,
        name='Current Position'
    ))
    fig.add_traces(initial_traces)

    # Set layout for animation controls
    fig.update_layout(
        title="DC Metro Speedrun Route Animation",
        updatemenus=[dict(
            type="buttons",
            showactive=False,
            y=1,
            x=1.1,
            xanchor="right",
            yanchor="top",
            buttons=[
                dict(label="Play",
                     method="animate",
                     args=[None, {"frame": {"duration": 250, "redraw": True},
                                  "fromcurrent": True,
                                  "transition": {"duration": 0}}]),
                dict(label="Pause",
                     method="animate",
                     args=[[None], {"frame": {"duration": 0, "redraw": False},
                                    "mode": "immediate",
                                    "transition": {"duration": 0}}])
            ]
        )]
    )

    # Set up frames
    fig.frames = frames

    # Set axis aspect ratio and limits
    fig.update_yaxes(scaleanchor="x", scaleratio=1)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.show()

def get_line_map(edges_lines_map):
    line_map = {}
    for edge, lines in edges_lines_map.items():
        from_node, to_node = edge
        # Store as a set of lines
        line_map[(from_node, to_node)] = set(lines)
        line_map[(to_node, from_node)] = set(lines)
    return line_map

line_map = get_line_map(edges_lines_map)

def metro_speedrun_path(G, start_node, line_map):
    unvisited = set(G.nodes())
    path = [start_node]
    current = start_node
    current_line = None
    total_time = 0

    unvisited.remove(current)

    while unvisited:
        candidates = []
        for neighbor in G.neighbors(current):
            if neighbor in unvisited:
                edge_weight = G[current][neighbor]['weight']
                lines = line_map.get((current, neighbor), set())
                transfer_penalty = 0
                if current_line and current_line not in lines:
                    transfer_penalty = G.nodes[current].get("transfer_time", 3)

                # ---- SMARTER BRANCH HEURISTIC ----
                # Compute how "branchy" or "leafy" this neighbor is
                unvisited_neighbors = [n for n in G.neighbors(neighbor) if n in unvisited and n != current]
                degree = len(list(G.neighbors(neighbor)))
                unvisited_degree = len(unvisited_neighbors)

                # If neighbor is a leaf, or almost a leaf, prefer visiting now
                # (higher bonus = higher priority, so we subtract this from the score)
                leaf_bonus = 0
                if unvisited_degree == 0:
                    leaf_bonus = -6  # real leaf
                elif unvisited_degree == 1:
                    leaf_bonus = -3  # near-leaf
                elif unvisited_degree == 2:
                    leaf_bonus = -1  # mini-branch

                # Combine total score (lower is better)
                score = edge_weight + transfer_penalty + leaf_bonus
                candidates.append((score, edge_weight + transfer_penalty, neighbor, lines))
        if not candidates:
            # If no unvisited neighbor, jump to closest unvisited via shortest path
            best_dist = float('inf')
            best_path = None
            for node in unvisited:
                try:
                    dist, route = nx.single_source_dijkstra(G, current, node, weight='weight')
                    if dist < best_dist:
                        best_dist = dist
                        best_path = route
                except nx.NetworkXNoPath:
                    continue
            # Step along that path to the next unvisited
            for prev, step in zip(best_path, best_path[1:]):
                path.append(step)
                if step in unvisited:
                    unvisited.remove(step)
                current = step
            continue
        # Pick the lowest-scoring candidate
        candidates.sort()
        score, move_cost, next_node, lines = candidates[0]
        path.append(next_node)
        if next_node in unvisited:
            unvisited.remove(next_node)
        current_line = (current_line if current_line in lines else list(lines)[0] if lines else None)
        current = next_node
        total_time += move_cost
    return path, round(total_time)



path, total_time = metro_speedrun_path(G, "Ashburn", line_map)
animate_route(G, path)

def summarize_path(path, line_map, G):
    print("\n📍 Route summary:")
    current_line = None

    def get_transfer_time(station):
        return G.nodes[station].get("transfer_time", 0)

    for i in range(1, len(path)):
        u = path[i - 1]
        v = path[i]
        segment_lines = line_map.get((u, v), {"Custom"})

        # Handle custom/manual edges (bus/walk)
        if "Custom" in segment_lines:
            if G.has_edge(u, v):
                path_name = G[u][v].get("custom_path", "Manual Connection")
                edge_weight = G[u][v].get("weight", "?")
            else:
                path_name = "Manual Connection"
                edge_weight = "?"
            print(f"🔁 Transfer via '{path_name}' from {u} to {v} ({edge_weight} min)")
            current_line = "Custom"
            continue

        # Choose line to stay on if possible
        prev_line = current_line
        if current_line in segment_lines:
            next_line = current_line
        else:
            next_line = sorted(segment_lines)[0]  # pick one
            if prev_line and prev_line != "Custom":
                transfer_time = get_transfer_time(u)
                print(f"🔁 Transferring at {u} from {prev_line} to {next_line} ({transfer_time} min)")
            else:
                print(f"🚇 Now taking {next_line} line from {u} to {v}")
        current_line = next_line

        # --- End-of-line check ---
        # If v is a terminus (degree 1), and previous station is its only neighbor
        v_neighbors = set(G.neighbors(v))
        if len(v_neighbors) == 1 and u in v_neighbors:
            transfer_time = get_transfer_time(v)
            print(f"⛔ End of line at {v} - Transferring Train ({transfer_time} min)")


summarize_path(path, line_map, G)
print(f"\n⏱️ Total predicted time: {format_time(total_time)}")
print("\n🛤️ Full path of stations visited:")
for i, station in enumerate(path):
    print(f"{i+1:3d}. {station}")


