import requests
import networkx as nx
import plotly.graph_objects as go
import plotly.io as pio
from collections import defaultdict
import json

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

# Plot lines
for edge, lines in edges_lines_map.items():
    from_node, to_node = edge
    x0, y0 = G.nodes[from_node]['pos']
    x1, y1 = G.nodes[to_node]['pos']
    weight = G[from_node][to_node].get("weight", "N/A")

    for line in lines:
        fig.add_trace(go.Scatter(
            x=[x0, x1],
            y=[y0, y1],
            mode='lines',
            line=dict(width=3, color=line_colors.get(line, 'gray')),
            hoverinfo='text',
            hovertext=f"{from_node} ↔ {to_node}<br>Line: {line}<br>Travel time: {weight} min",
            name=f"{line} Line",
            legendgroup=line,
            showlegend=False
        ))

# Plot custom (manual) edges in purple
for custom in custom_edges:
    u = custom["station1"]
    v = custom["station2"]
    x0, y0 = G.nodes[u]["pos"]
    x1, y1 = G.nodes[v]["pos"]
    name = custom["pathName"]
    weight = custom["time"]

    fig.add_trace(go.Scatter(
        x=[x0, x1],
        y=[y0, y1],
        mode='lines',
        line=dict(width=3, color="purple", dash="dot"),
        hoverinfo='text',
        hovertext=f"{name}<br>{u} ↔ {v}<br>Travel time: {weight} min",
        name=name,
        legendgroup="custom",
        showlegend=True
    ))

# Add invisible hover markers for custom paths
for custom in custom_edges:
    u = custom["station1"]
    v = custom["station2"]
    x0, y0 = G.nodes[u]["pos"]
    x1, y1 = G.nodes[v]["pos"]
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2

    hover = f"{custom['pathName']}<br>{u} ↔ {v}<br>Travel time: {custom['time']} min"
    fig.add_trace(go.Scatter(
        x=[mx],
        y=[my],
        mode='markers',
        marker=dict(size=10, color='rgba(128,0,128,0)'),  # invisible purple
        hoverinfo='text',
        hovertext=[hover],
        showlegend=False
    ))

# Add one legend entry per line
for line in line_colors:
    fig.add_trace(go.Scatter(
        x=[None], y=[None],
        mode='lines',
        line=dict(width=3, color=line_colors[line]),
        name=f"{line} Line",
        legendgroup=line
    ))

# Plot station nodes
node_x, node_y, node_text, node_hover = [], [], [], []

for node in G.nodes():
    x, y = G.nodes[node]['pos']
    node_x.append(x)
    node_y.append(y)
    node_text.append(node)  # just the name for map label

    codes = G.nodes[node]["codes"]
    served_lines = set()
    for code in codes:
        for line, station_list in line_station_codes.items():
            if code in station_list:
                served_lines.add(line)
    line_list = ", ".join(sorted(served_lines))

    wait_time = 1
    transfer_time = G.nodes[node].get("transfer_time", 0)

    hover = (
        f"{node}<br>"
        f"Lines Served: {line_list}<br>"
        f"Wait Time: {wait_time} min<br>"
        f"Transfer Time: {transfer_time} min"
    )
    node_hover.append(hover)

fig.add_trace(go.Scatter(
    x=node_x,
    y=node_y,
    mode='markers+text',
    marker=dict(size=6, color='black'),
    text=node_text,              # visible label = just station name
    hovertext=node_hover,        # hover shows full info
    hoverinfo='text',
    textposition="top center",
    textfont=dict(family="Helvetica", size=12, color="black"),
    name="Stations"
))



# Midpoint hover markers
mid_x, mid_y, mid_text = [], [], []
for edge in edges_lines_map:
    from_node, to_node = edge
    x0, y0 = G.nodes[from_node]['pos']
    x1, y1 = G.nodes[to_node]['pos']
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2

    weight = G[from_node][to_node].get("weight", "N/A")
    lines = sorted(edges_lines_map[edge])
    line_list = ", ".join(lines)

    mid_x.append(mx)
    mid_y.append(my)
    mid_text.append(f"{from_node} ↔ {to_node}<br>Lines: {line_list}<br>Travel time: {weight} min")

fig.add_trace(go.Scatter(
    x=mid_x,
    y=mid_y,
    mode='markers',
    marker=dict(size=10, color='rgba(0,0,0,0)'),
    hoverinfo='text',
    hovertext=mid_text,
    showlegend=False,
    name="Edge Info"
))

fig.update_layout(
    title="DC Metro System Graph (Color-coded by Line)",
    showlegend=True,
    margin=dict(l=0, r=0, t=30, b=0),
    plot_bgcolor='white',
    font=dict(family="Helvetica", size=12, color="black"),
    legend=dict(
        bgcolor='rgba(255,255,255,0.7)',
        bordercolor='black',
        borderwidth=1
    )
)

def get_line_map(edges_lines_map):
    line_map = {}
    for edge, lines in edges_lines_map.items():
        from_node, to_node = edge
        # Store as a set of lines
        line_map[(from_node, to_node)] = set(lines)
        line_map[(to_node, from_node)] = set(lines)
    return line_map

def format_time(minutes):
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours} hr {mins} min" if hours else f"{mins} min"

def tsp_greedy_visit_all(G, start_node, line_map):
    visited = set()
    current = start_node
    total_time = 0
    path = [current]
    current_line = None

    visited.add(current)

    def get_travel_cost(u, v, line_from):
        if not G.has_edge(u, v):
            print(f"❌ Tried to traverse nonexistent edge: {u} ↔ {v}")
            return float('inf'), None, 0
        base = G[u][v]["weight"]
        new_line = line_map.get((u, v))
        transfer = G.nodes[u].get("transfer_time", 0) if line_from and new_line and line_from != new_line else 0
        return base + transfer, new_line, transfer

    while len(visited) < len(G.nodes):
        unvisited_neighbors = [n for n in G.neighbors(current) if n not in visited]

        if unvisited_neighbors:
            candidates = unvisited_neighbors
        else:
            # Backtrack: Find shortest valid path to next unvisited station
            min_path = None
            min_cost = float("inf")
            for target in G.nodes():
                if target in visited:
                    continue
                try:
                    length, route = nx.single_source_dijkstra(G, current, target, weight="weight")
                    if length < min_cost:
                        min_cost = length
                        min_path = route
                except nx.NetworkXNoPath:
                    continue

            if not min_path:
                print("❌ No way to reach remaining unvisited stations.")
                break

            # Step through each edge along the min_path
            for i in range(1, len(min_path)):
                u, v = min_path[i - 1], min_path[i]
                cost, new_line, transfer_time = get_travel_cost(u, v, current_line)
                if cost == float('inf'):
                    print(f"❌ No edge between {u} and {v}, aborting this path.")
                    break
                total_time += cost
                current_line = new_line
                if v not in visited:
                    visited.add(v)
                path.append(v)
                current = v
            continue

        # Choose best candidate neighbor as before
        best_next = None
        best_score = float('inf')
        best_line = None
        best_transfer = 0

        for neighbor in candidates:
            cost, new_line, transfer_time = get_travel_cost(current, neighbor, current_line)
            if cost == float('inf'):
                continue  # Ignore invalid moves

            unvisited_fanout = sum(1 for n in G.neighbors(neighbor) if n not in visited)
            penalty = -2 if unvisited_fanout <= 1 else 0

            score = cost + penalty

            if score < best_score:
                best_score = score
                best_next = neighbor
                best_line = new_line
                best_transfer = transfer_time

        if best_next is None:
            print("❌ Could not find a valid move from", current)
            break

        if best_line != current_line and current_line is not None:
            print(f"🔁 Transferring at {current}: {current_line} → {best_line} (+{best_transfer} min)")

        total_time += best_score
        current = best_next
        current_line = best_line
        visited.add(current)
        path.append(current)

    return path, round(total_time)





line_map = get_line_map(edges_lines_map)
path, total_time = tsp_greedy_visit_all(G, "Ashburn", line_map)

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
            path_name = G[u][v].get("custom_path", "Manual Connection")
            print(f"🔁 Transfer via '{path_name}' from {u} to {v} ({G[u][v]['weight']} min)")
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

fig.show()
