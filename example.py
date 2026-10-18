"""Quick demo: nearby stops, departures and vehicles around Aarhus H."""

import asyncio

from midttrafik_live import MidttrafikLiveClient

LAT, LON = 56.1503, 10.2045  # Aarhus H


async def main() -> None:
    async with MidttrafikLiveClient() as client:
        stops = await client.get_stops_nearby(LAT, LON, radius=200)
        for s in stops[:5]:
            print(f"{s.number}  {s.name}  ({s.distance:.0f} m)")

        # Pick a bus stop (the first hit, 008600053, is the DSB train station).
        stop = await client.get_stop("751001602")  # Aarhus Banegårdsplads
        print(f"\nDepartures from {stop.name}:")
        departures = await client.get_departures(stop.number)
        for d in departures[:8]:
            delay = f" (+{d.delay_minutes} min)" if d.delay_minutes else ""
            rt = "" if d.has_realtime else " [scheduled]"
            cancelled = " CANCELLED" if d.cancelled else ""
            print(f"  {d.expected:%H:%M}  {d.line:>5}  {d.direction}{delay}{rt}{cancelled}")

        if departures:
            trip = await client.get_journey_details(departures[0].journey_ref)
            print(f"\nTrip of line {departures[0].line}: {len(trip)} stops, "
                  f"{trip[0].name} -> {trip[-1].name}")

        print("\nVehicles within 1 km:")
        for b in await client.get_buses_nearby(LAT, LON, radius=1000):
            print(f"  #{b.id}  {b.line:>5} -> {b.direction}  @ {b.latitude:.5f},{b.longitude:.5f}")


asyncio.run(main())
