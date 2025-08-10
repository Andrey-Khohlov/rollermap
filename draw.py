import dash
import dash_leaflet as dl
from dash import  html
from dash.dependencies import Input, Output, State
import json

app = dash.Dash(__name__)

# Создаем карту с инструментом рисования
app.layout = html.Div([
    dl.Map(
        center=[55.75, 37.61],
        zoom=12,
        children=[
            dl.TileLayer(),
            dl.FeatureGroup([
                dl.EditControl(
                    id="draw_tool",
                    draw={
                        "polyline": True,
                        "polygon": False,
                        "rectangle": False,
                        "circle": False,
                        "marker": False,
                    },
                )
            ])
        ],
        style={'width': '100%', 'height': '80vh'}
    ),
    html.Div(id="output"),  # Здесь будут выводиться данные
])

# Сохраняем нарисованные линии
@app.callback(
    Output("output", "children"),
    Input("draw_tool", "geojson"),
    prevent_initial_call=True
)
def save_drawn_data(geojson):
    if geojson:
        with open("saved_obstructions.json", "w") as f:
            json.dump(geojson, f, ensure_ascii=False, indent=4)
        return "Данные сохранены в saved_obstructions.json"
    return ""

if __name__ == "__main__":
    app.run(debug=True)