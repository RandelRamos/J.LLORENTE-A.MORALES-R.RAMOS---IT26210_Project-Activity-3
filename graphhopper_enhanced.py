import datetime
import os
import sys
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import readchar
import requests
from colorama import Fore, Style, init
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Initialize Colorama and Rich Console
init(autoreset=True)
console = Console()

# Load environment variables explicitly from api_keys.env
load_dotenv("api_keys.env")


# ==============================================================================
# 1. SECURITY, RESILIENCE & TECHNICAL ARCHITECTURE
# ==============================================================================

class KeyManager:
    """Handles API key storage, failover, and rotation without hardcoded fallbacks."""

    def __init__(self):
        self.keys = self._load_keys()
        self.current_index = 0

    def _load_keys(self) -> List[str]:
        keys = []
        idx = 1
        while True:
            k = os.getenv(f"GRAPH_HOPPER_KEY_{idx}")
            if k:
                keys.append(k)
                idx += 1
            else:
                break
        
        if not keys and os.getenv("GRAPH_HOPPER_KEY"):
            keys.append(os.getenv("GRAPH_HOPPER_KEY"))

        if not keys:
            console.print(
                "[bold red]Error:[/bold red] No API keys found in 'api_keys.env'. "
                "Please add GRAPH_HOPPER_KEY or GRAPH_HOPPER_KEY_1 to api_keys.env."
            )
            sys.exit(1)

        return keys

    def get_key(self) -> str:
        return self.keys[self.current_index]

    def rotate_key(self) -> bool:
        """Rotates to the next available API key if present."""
        if len(self.keys) <= 1:
            return False
        old_idx = self.current_index
        self.current_index = (self.current_index + 1) % len(self.keys)
        console.print(
            f"[yellow]Key #{old_idx + 1} exhausted/failed. Rotated to Key #{self.current_index + 1}.[/yellow]"
        )
        return True


key_mgr = KeyManager()


def safe_api_get(base_url: str, params: Dict[str, Any]) -> Tuple[int, Optional[Dict[str, Any]]]:
    """Wraps network calls with try-except blocks and handles key failover."""
    attempts = 0
    max_attempts = len(key_mgr.keys)

    while attempts < max_attempts:
        params["key"] = key_mgr.get_key()
        try:
            response = requests.get(base_url, params=params, timeout=10)
            status_code = response.status_code

            if status_code in (401, 403, 429):
                console.print(
                    f"[red]API Key Error (Status {status_code}). Attempting failover...[/red]"
                )
                if key_mgr.rotate_key():
                    attempts += 1
                    continue

            try:
                json_data = response.json()
            except Exception:
                json_data = None

            return status_code, json_data

        except requests.exceptions.RequestException as e:
            console.print(f"[bold red]Network Connection Error:[/bold red] {e}")
            return 0, None

    console.print("[bold red]All available API keys have been exhausted or failed.[/bold red]")
    return 0, None


def geocoding(location_query: str) -> Tuple[int, Optional[Dict[str, Any]]]:
    """Retrieves geocoding results."""
    geocode_url = "https://graphhopper.com/api/1/geocode"
    params = {"q": location_query, "limit": "5"}
    status_code, json_data = safe_api_get(geocode_url, params)
    return status_code, json_data


# ==============================================================================
# 2. UI & INTERACTIVE INPUT WORKFLOWS
# ==============================================================================

def prompt_confirm_entered_text(entered_text: str) -> bool:
    """Confirmation prompt executed directly after typing and entering location text."""
    console.print(f"\nEntered: [bold cyan]{entered_text}[/bold cyan]")
    console.print("[yellow]Continue with entered location?[/yellow]")
    console.print("  • Press [Enter] to continue")
    console.print("  • Press [Backspace] to re-enter")
    
    while True:
        key = readchar.readkey()
        if key in (readchar.key.ENTER, readchar.key.CR, "\r", "\n"):
            return True
        elif key in (readchar.key.BACKSPACE, "\x08", "\x7f"):
            return False


def prompt_confirm_menu(value_display: str) -> bool:
    """Confirmation prompt when making a selection from a list of options."""
    console.print(f"\nSelected: [bold cyan]{value_display}[/bold cyan]")
    console.print("[yellow]Continue with selected option?[/yellow]")
    console.print("  • Press [Enter] to continue")
    console.print("  • Press [Backspace] to reselect")
    
    while True:
        key = readchar.readkey()
        if key in (readchar.key.ENTER, readchar.key.CR, "\r", "\n"):
            return True
        elif key in (readchar.key.BACKSPACE, "\x08", "\x7f"):
            return False


def interactive_vehicle_selector() -> str:
    """Vertical menu selection for vehicle profile with confirmation interface."""
    vehicles = {"1": ("car", "Car"), "2": ("bike", "Bike"), "3": ("foot", "Foot")}
    while True:
        console.print("\n[bold yellow]--- Select Vehicle Profile ---[/bold yellow]")
        for k, v in vehicles.items():
            console.print(f"  • [{k}] {v[1]}")
        
        choice = input("Enter option number (1-3) or 'q' to quit: ").strip().lower()
        if choice in ("q", "quit"):
            sys.exit(0)
        
        if choice in vehicles:
            profile_key, profile_label = vehicles[choice]
            if prompt_confirm_menu(profile_label):
                return profile_key
        else:
            console.print("[red]Invalid selection. Please try again.[/red]")


def interactive_unit_selector() -> str:
    """Vertical menu selection for distance measurement unit."""
    units = {"1": ("miles", "Miles"), "2": ("km", "Kilometers"), "3": ("both", "Both (Miles & KM)")}
    while True:
        console.print("\n[bold yellow]--- Select Distance Display Units ---[/bold yellow]")
        for k, v in units.items():
            console.print(f"  • [{k}] {v[1]}")
        
        choice = input("Enter option number (1-3): ").strip()
        if choice in units:
            unit_key, unit_label = units[choice]
            if prompt_confirm_menu(unit_label):
                return unit_key
        else:
            console.print("[red]Invalid selection. Please try again.[/red]")


def interactive_waypoint_prompt() -> bool:
    """Vertical menu selection for adding an intermediate stop/waypoint."""
    options = {"1": (True, "Yes - Add Waypoint"), "2": (False, "No - Skip Waypoints")}
    while True:
        console.print("\n[bold yellow]--- Add Intermediate Stop/Waypoint? ---[/bold yellow]")
        for k, v in options.items():
            console.print(f"  • [{k}] {v[1]}")
        
        choice = input("Enter option number (1-2): ").strip()
        if choice in options:
            should_add, label = options[choice]
            if prompt_confirm_menu(label):
                return should_add
        else:
            console.print("[red]Invalid selection. Please try again.[/red]")


def interactive_export_prompt() -> bool:
    """Vertical menu selection for exporting itinerary details to text file."""
    options = {"1": (True, "Yes - Export to File"), "2": (False, "No - Do Not Export")}
    while True:
        console.print("\n[bold yellow]--- Export Itinerary to Text File? ---[/bold yellow]")
        for k, v in options.items():
            console.print(f"  • [{k}] {v[1]}")
        
        choice = input("Enter option number (1-2): ").strip()
        if choice in options:
            should_export, label = options[choice]
            if prompt_confirm_menu(label):
                return should_export
        else:
            console.print("[red]Invalid selection. Please try again.[/red]")


def interactive_repeat_prompt() -> bool:
    """Vertical menu selection for planning another route or exiting."""
    options = {"1": (True, "Yes - Plan Another Route"), "2": (False, "No - Exit Application")}
    while True:
        console.print("\n[bold yellow]--- Plan Another Route? ---[/bold yellow]")
        for k, v in options.items():
            console.print(f"  • [{k}] {v[1]}")
        
        choice = input("Enter option number (1-2): ").strip()
        if choice in options:
            should_repeat, label = options[choice]
            if prompt_confirm_menu(label):
                return should_repeat
        else:
            console.print("[red]Invalid selection. Please try again.[/red]")


def interactive_location_input(prompt_label: str, section_header: Optional[str] = None) -> Dict[str, Any]:
    """Handles location text input, confirmation, geocoding lookup, and selection."""
    while True:
        if section_header:
            console.print(f"\n[bold yellow]{section_header}[/bold yellow]")
            loc_str = input(f"Enter {prompt_label}: ").strip()
        else:
            loc_str = input(f"\nEnter {prompt_label}: ").strip()
            
        if not loc_str:
            continue
        if loc_str.lower() in ("q", "quit"):
            sys.exit(0)

        if not prompt_confirm_entered_text(loc_str):
            continue

        status, data = geocoding(loc_str)
        if status != 200 or not data or not data.get("hits"):
            console.print(f"[red]Failed to find location for '{loc_str}'. Status: {status}[/red]")
            continue

        hits = data["hits"]
        selected_hit = None

        if len(hits) == 1:
            candidate_hit = hits[0]
            name = candidate_hit.get("name", "")
            state = candidate_hit.get("state", "")
            country = candidate_hit.get("country", "")
            desc = ", ".join(filter(None, [name, state, country]))
            
            if prompt_confirm_menu(desc):
                selected_hit = candidate_hit
            else:
                continue
        else:
            reselect_outer = False
            while True:
                console.print(f"\n[yellow]Multiple matches found for '{loc_str}':[/yellow]")
                for idx, hit in enumerate(hits, 1):
                    name = hit.get("name", "")
                    state = hit.get("state", "")
                    country = hit.get("country", "")
                    osm_val = hit.get("osm_value", "")
                    loc_desc = ", ".join(filter(None, [name, state, country]))
                    console.print(f"  • [{idx}] {loc_desc} [dim]({osm_val})[/dim]")
                
                sel = input("Select correct location number: ").strip()
                if sel.isdigit() and 1 <= int(sel) <= len(hits):
                    candidate_hit = hits[int(sel) - 1]
                    
                    c_name = candidate_hit.get("name", "")
                    c_state = candidate_hit.get("state", "")
                    c_country = candidate_hit.get("country", "")
                    candidate_desc = ", ".join(filter(None, [c_name, c_state, c_country]))
                    
                    if prompt_confirm_menu(candidate_desc):
                        selected_hit = candidate_hit
                        break
                    else:
                        continue
                else:
                    console.print("[red]Invalid choice.[/red]")

            if reselect_outer:
                continue

        name = selected_hit.get("name", "")
        state = selected_hit.get("state", "")
        country = selected_hit.get("country", "")
        formatted_name = ", ".join(filter(None, [name, state, country]))

        return {
            "display": formatted_name,
            "lat": selected_hit["point"]["lat"],
            "lng": selected_hit["point"]["lng"],
            "country": country,
        }


# ==============================================================================
# 3. FORMATTING & ANALYTICS UTILITIES
# ==============================================================================

def create_standard_table(title: str) -> Table:
    """Factory helper to build Rich tables using standard default styling."""
    return Table(title=title)


def format_distance(meters: float, unit_choice: str) -> str:
    """Converts meters to miles, km, or dual display format."""
    km = meters / 1000.0
    miles = km / 1.60934
    if unit_choice == "miles":
        return f"{miles:.2f} mi"
    elif unit_choice == "km":
        return f"{km:.2f} km"
    else:
        return f"{miles:.2f} mi / {km:.2f} km"


def format_duration(ms: float) -> str:
    """Formats milliseconds into 00h:00m:00s format."""
    total_sec = int(ms / 1000)
    hr = total_sec // 3600
    mn = (total_sec % 3600) // 60
    sc = total_sec % 60
    return f"{hr:02d}h:{mn:02d}m:{sc:02d}s"


def calculate_analytics(
    dist_meters: float, duration_ms: float, vehicle: str
) -> Dict[str, Any]:
    """Calculates fuel/cost, carbon emissions/savings, calories, and ETA."""
    km = dist_meters / 1000.0
    miles = km / 1.60934
    hours = (duration_ms / 1000.0) / 3600.0

    if vehicle == "car":
        fuel_gallons = miles / 25.0
        fuel_cost = fuel_gallons * 3.50
        cost_str = f"${fuel_cost:.2f} USD ({fuel_gallons:.2f} gal fuel)"
        co2_kg = miles * 0.404
        co2_str = f"{co2_kg:.2f} kg CO2"
        calories = int(hours * 60)
    elif vehicle == "bike":
        cost_str = "$0.00 (Active Transport)"
        co2_saved = miles * 0.404
        co2_str = f"0.0 kg (Saved {co2_saved:.2f} kg CO2 vs Car!)"
        calories = int(miles * 45)
    else:  # Foot
        cost_str = "$0.00 (Active Transport)"
        co2_saved = miles * 0.404
        co2_str = f"0.0 kg (Saved {co2_saved:.2f} kg CO2 vs Car!)"
        calories = int(miles * 80)

    now = datetime.datetime.now()
    eta = now + datetime.timedelta(seconds=int(duration_ms / 1000.0))
    eta_str = eta.strftime("%I:%M %p (%Y-%m-%d)")

    return {
        "Cost": cost_str,
        "CO2 Emissions": co2_str,
        "Calories Burned": f"~{calories} kcal",
        "Projected ETA": eta_str,
    }


# ==============================================================================
# 4. UPDATED ROUTE SEGMENT ANALYSIS (CORRECT LEG ALLOCATION)
# ==============================================================================

def generate_segment_breakdown(
    instructions: List[Dict[str, Any]], all_stops: List[Dict[str, Any]], unit_choice: str
) -> List[List[str]]:
    """Analyzes instructions to construct a leg-by-leg breakdown showing distance,
    estimated speed, driving conditions, and recommended actions."""
    
    num_legs = len(all_stops) - 1
    leg_instructions: List[List[Dict[str, Any]]] = [[] for _ in range(num_legs)]
    
    current_leg = 0

    # 1. First Pass: Detect arrival signposts (sign == 4 or text indicating waypoint arrival)
    for inst in instructions:
        leg_instructions[current_leg].append(inst)
        
        text_lower = inst.get("text", "").lower()
        sign = inst.get("sign")
        
        # Check if instruction indicates arrival at a waypoint or intermediate destination
        is_arrival = (
            sign in (4, 5) or
            "arrive at" in text_lower or
            "reached waypoint" in text_lower or
            "reached intermediate destination" in text_lower or
            "via point" in text_lower
        )
        
        if is_arrival and current_leg < num_legs - 1:
            current_leg += 1

    # 2. Fallback Pass: If all instructions ended up in Leg 1 due to GraphHopper formatting
    non_empty_legs = sum(1 for leg in leg_instructions if leg)
    if num_legs > 1 and non_empty_legs == 1:
        leg_instructions = [[] for _ in range(num_legs)]
        
        # Group instructions proportionally or by interval indices
        total_insts = len(instructions)
        if total_insts >= num_legs:
            chunk_size = total_insts // num_legs
            for i, inst in enumerate(instructions):
                leg_idx = min(i // chunk_size, num_legs - 1)
                leg_instructions[leg_idx].append(inst)
        else:
            for i, inst in enumerate(instructions):
                leg_idx = min(i, num_legs - 1)
                leg_instructions[leg_idx].append(inst)

    rows = []
    for idx in range(num_legs):
        from_name = all_stops[idx]["display"].split(",")[0]
        to_name = all_stops[idx + 1]["display"].split(",")[0]
        segment_label = f"Leg {idx + 1}: {from_name} → {to_name}"
        
        leg_insts = leg_instructions[idx]
        leg_dist = sum(inst.get("distance", 0.0) for inst in leg_insts)
        leg_time = sum(inst.get("time", 0.0) for inst in leg_insts)
        
        dist_str = format_distance(leg_dist, unit_choice)
        dur_str = format_duration(leg_time)
        
        # Speed calculations
        km = leg_dist / 1000.0
        hours = (leg_time / 1000.0) / 3600.0 if leg_time > 0 else 0
        avg_speed_kmh = (km / hours) if hours > 0 else 0
        avg_speed_mph = avg_speed_kmh / 1.60934

        if unit_choice == "miles":
            speed_str = f"{avg_speed_mph:.1f} mph"
        elif unit_choice == "km":
            speed_str = f"{avg_speed_kmh:.1f} km/h"
        else:
            speed_str = f"{avg_speed_mph:.1f} mph / {avg_speed_kmh:.1f} km/h"

        # Classify environment & recommendations based on average velocity
        if avg_speed_kmh >= 75:
            condition = "Highway / Expressway"
            advice = "Free flow; ideal for cruising"
        elif avg_speed_kmh >= 35:
            condition = "Suburban Corridor"
            advice = "Moderate traffic; watch for signals"
        elif avg_speed_kmh > 0:
            condition = "Urban Street / Slow Zone"
            advice = "Expect dense traffic or pedestrian crossings"
        else:
            condition = "Stationary / Local Stop"
            advice = "N/A"

        rows.append([segment_label, dist_str, dur_str, speed_str, condition, advice])

    return rows


def generate_shareable_url(points: List[Tuple[float, float]], vehicle: str = "car") -> str:
    """Generates a Google Maps shareable directions link."""
    if not points:
        return ""
    
    origin = f"{points[0][0]},{points[0][1]}"
    destination = f"{points[-1][0]},{points[-1][1]}"
    
    travel_modes = {"car": "driving", "bike": "bicycling", "foot": "walking"}
    mode = travel_modes.get(vehicle.lower(), "driving")
    
    base_url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={destination}&travelmode={mode}"
    
    if len(points) > 2:
        waypoints_str = "|".join([f"{p[0]},{p[1]}" for p in points[1:-1]])
        base_url += f"&waypoints={urllib.parse.quote(waypoints_str)}"
        
    return base_url


def export_itinerary_to_file(
    summary_data: List[List[str]],
    directions_data: List[List[str]],
    analytics_data: List[List[str]],
    segment_data: List[List[str]],
    filename: str = "trip_itinerary.txt",
):
    """Saves formatted itinerary details to a local text file."""
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write("=====================================================\n")
            f.write("             GRAPH HOPPER TRIP ITINERARY             \n")
            f.write("=====================================================\n\n")

            f.write("--- ROUTE SUMMARY ---\n")
            for row in summary_data:
                f.write(f"{row[0]}: {row[1]}\n")

            f.write("\n--- METRICS & ANALYTICS ---\n")
            for row in analytics_data:
                f.write(f"{row[0]}: {row[1]}\n")

            f.write("\n--- ROUTE SEGMENT BREAKDOWN ---\n")
            for row in segment_data:
                f.write(f"{row[0]} | Distance: {row[1]} | Duration: {row[2]} | Avg Speed: {row[3]} | Type: {row[4]}\n")

            f.write("\n--- TURN-BY-TURN DIRECTIONS ---\n")
            for row in directions_data:
                f.write(f"Step {row[0]}: {row[1]} ({row[2]})\n")

            f.write("\n=====================================================\n")
        console.print(f"\n[bold green]Itinerary successfully exported to '{filename}'[/bold green]")
    except Exception as e:
        console.print(f"[red]Failed to export file: {e}[/red]")


# ==============================================================================
# MAIN APPLICATION LOOP
# ==============================================================================

def main():
    console.print(
        Panel.fit(
            "[bold green]GraphHopper REST API Application - Enhanced Edition[/bold green]\n"
            "[dim]Route Planning, Multi-Point Navigation & Analytics[/dim]",
            border_style="green",
        )
    )

    while True:
        # 1. Select Vehicle Menu
        vehicle = interactive_vehicle_selector()

        # 2. Select Unit Menu
        unit_choice = interactive_unit_selector()

        # 3. Starting Location Input
        origin = interactive_location_input("Starting Location", section_header="--- Starting Location ---")

        # 4. Multi-Point Waypoint Support
        waypoints: List[Dict[str, Any]] = []
        while True:
            if interactive_waypoint_prompt():
                wp = interactive_location_input(f"Waypoint #{len(waypoints) + 1}")
                waypoints.append(wp)
            else:
                break

        # 5. Destination Location Input
        destination = interactive_location_input("Destination Location", section_header="--- Destination Location ---")

        all_stops = [origin] + waypoints + [destination]

        route_url = "https://graphhopper.com/api/1/route"

        console.print("\n[cyan]Fetching optimal route from GraphHopper API...[/cyan]")

        key = key_mgr.get_key()
        param_dict = {"key": key, "vehicle": vehicle, "instructions": "true"}
        query_str = urllib.parse.urlencode(param_dict)
        for pt in all_stops:
            query_str += f"&point={pt['lat']}%2C{pt['lng']}"

        full_url = f"{route_url}?{query_str}"

        try:
            res = requests.get(full_url, timeout=10)
            status_code = res.status_code
            route_json = res.json()
        except Exception as e:
            console.print(f"[bold red]API Request Failed:[/bold red] {e}")
            continue

        status_color = "green" if status_code == 200 else "red"
        console.print(f"Routing API Status: [{status_color}]{status_code}[/{status_color}]\n")

        if status_code != 200:
            msg = route_json.get("message", "Unknown Error")
            console.print(f"[bold red]Error Message:[/bold red] {msg}")
            continue

        path = route_json["paths"][0]
        total_dist = path["distance"]
        total_time = path["time"]
        instructions = path.get("instructions", [])

        # Table 1: Route Summary
        summary_table = create_standard_table("[bold yellow]--- Route Summary ---[/bold yellow]")
        summary_table.add_column("Route Metrics")
        summary_table.add_column("Route Metrics Data")

        via_str = " -> ".join([w["display"] for w in waypoints]) if waypoints else "Direct"
        summary_rows = [
            ["Origin", origin["display"]],
            ["Waypoints", via_str],
            ["Destination", destination["display"]],
            ["Vehicle Profile", vehicle.capitalize()],
            ["Total Distance", format_distance(total_dist, unit_choice)],
            ["Trip Duration", format_duration(total_time)],
        ]
        for row in summary_rows:
            summary_table.add_row(row[0], row[1])
        console.print(summary_table)
        console.print()

        # Table 2: Analytics & Trip Metrics
        analytics = calculate_analytics(total_dist, total_time, vehicle)
        analytics_table = create_standard_table("[bold yellow]--- Analytics and Trip Metrics ---[/bold yellow]")
        analytics_table.add_column("Trip Metrics")
        analytics_table.add_column("Trip Metrics Data")

        analytics_rows = [[k, v] for k, v in analytics.items()]
        for row in analytics_rows:
            analytics_table.add_row(row[0], row[1])
        console.print(analytics_table)
        console.print()

        # Table 3: Driving Conditions & Route Segment Breakdown (Updated)
        segment_rows = generate_segment_breakdown(instructions, all_stops, unit_choice)
        segment_table = create_standard_table("[bold yellow]--- Driving Conditions & Route Segment Breakdown ---[/bold yellow]")
        segment_table.add_column("Route Leg")
        segment_table.add_column("Distance")
        segment_table.add_column("Duration")
        segment_table.add_column("Est. Avg Speed")
        segment_table.add_column("Road Environment")
        segment_table.add_column("Recommendation")

        for row in segment_rows:
            segment_table.add_row(*row)
        console.print(segment_table)
        console.print()

        # Table 4: Turn-by-Turn Directions
        directions_table = create_standard_table("[bold yellow]--- Turn-by-turn Directions ---[/bold yellow]")
        directions_table.add_column("Step No.")
        directions_table.add_column("Direction Maneuver")
        directions_table.add_column("Direction Distance")

        directions_rows = []
        for idx, inst in enumerate(instructions, 1):
            text = inst.get("text", "")
            step_dist = inst.get("distance", 0.0)
            dist_str = format_distance(step_dist, unit_choice)

            directions_rows.append([str(idx), text, dist_str])
            directions_table.add_row(str(idx), text, dist_str)

        console.print(directions_table)
        console.print()

        # Google Maps Shareable Link
        coords = [(pt["lat"], pt["lng"]) for pt in all_stops]
        share_url = generate_shareable_url(coords, vehicle)
        console.print(f"\n[bold yellow]Google Maps Shareable Route Link:[/bold yellow]\n{share_url}\n")

        # Export Option
        if interactive_export_prompt():
            export_itinerary_to_file(summary_rows, directions_rows, analytics_rows, segment_rows)

        # Continue loop or quit
        if not interactive_repeat_prompt():
            console.print("\n[bold green]Thank you for using GraphHopper Routing Utilities![/bold green]")
            sys.exit(0)


if __name__ == "__main__":
    main()