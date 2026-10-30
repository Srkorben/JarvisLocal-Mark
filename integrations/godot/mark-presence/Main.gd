extends Node3D

const STATE_COLORS := {
	"offline": Color(0.30, 0.35, 0.42),
	"loading": Color(0.35, 0.55, 1.00),
	"idle": Color(0.20, 0.82, 0.95),
	"recording": Color(0.20, 1.00, 0.68),
	"transcribing": Color(0.70, 0.50, 1.00),
	"processing": Color(1.00, 0.68, 0.20),
	"speaking": Color(0.25, 0.92, 1.00),
	"cancelling": Color(1.00, 0.48, 0.18),
	"error": Color(1.00, 0.22, 0.25),
}

var _endpoint := ""
var _token := ""
var _state := "offline"
var _transcript := ""
var _response := ""
var _error := ""
var _smoke_test := false
var _elapsed := 0.0
var _core: MeshInstance3D
var _rings: Array[MeshInstance3D] = []
var _core_material: StandardMaterial3D
var _ring_materials: Array[StandardMaterial3D] = []
var _state_label: Label
var _detail_label: Label
var _http: HTTPRequest
var _poll_timer: Timer


func _ready() -> void:
	_endpoint = OS.get_environment("MARK_CONTROL_CENTER_URL").trim_suffix("/")
	_token = OS.get_environment("MARK_CONTROL_CENTER_TOKEN")
	_smoke_test = "--smoke-test" in OS.get_cmdline_user_args()
	if _endpoint.is_empty() or _token.is_empty():
		_load_endpoint_file()
	_build_scene()
	_http.request_completed.connect(_on_request_completed)
	_poll_timer.timeout.connect(_poll_presence)
	_poll_presence()


func _load_endpoint_file() -> void:
	var arguments := OS.get_cmdline_user_args()
	var marker := arguments.find("--endpoint-file")
	if marker < 0 or marker + 1 >= arguments.size():
		return
	var path: String = arguments[marker + 1]
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return
	var payload = JSON.parse_string(file.get_as_text())
	if not payload is Dictionary:
		return
	var port := int(payload.get("port", 0))
	var bind := str(payload.get("bind", ""))
	var candidate_token := str(payload.get("token", ""))
	if bind != "127.0.0.1" or port < 1 or port > 65535 or candidate_token.is_empty():
		return
	_endpoint = "http://127.0.0.1:%s" % port
	_token = candidate_token


func _process(delta: float) -> void:
	_elapsed += delta
	var intensity := _state_intensity(_state)
	_core.rotation.y += delta * (0.22 + intensity * 0.65)
	_core.rotation.x = sin(_elapsed * 0.37) * 0.16
	var pulse := 1.0 + sin(_elapsed * (1.8 + intensity * 2.8)) * (0.025 + intensity * 0.055)
	_core.scale = Vector3.ONE * pulse
	for index in _rings.size():
		var ring := _rings[index]
		ring.rotation.z += delta * (0.20 + index * 0.13) * (-1.0 if index % 2 else 1.0)
		ring.rotation.x = deg_to_rad(66.0 + index * 17.0) + sin(_elapsed * 0.45 + index) * 0.08
	_update_materials()


func _build_scene() -> void:
	var camera := Camera3D.new()
	camera.position = Vector3(0.0, 0.0, 6.6)
	add_child(camera)
	camera.look_at(Vector3.ZERO)

	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-35.0, -28.0, 0.0)
	light.light_energy = 1.35
	add_child(light)

	var fill := OmniLight3D.new()
	fill.position = Vector3(0.0, 1.2, 2.8)
	fill.omni_range = 8.0
	fill.light_energy = 2.0
	fill.light_color = Color(0.22, 0.78, 1.0)
	add_child(fill)

	_core = MeshInstance3D.new()
	var sphere := SphereMesh.new()
	sphere.radius = 1.0
	sphere.height = 2.0
	sphere.radial_segments = 64
	sphere.rings = 32
	_core.mesh = sphere
	_core_material = StandardMaterial3D.new()
	_core.material_override = _core_material
	add_child(_core)

	for index in 3:
		var ring := MeshInstance3D.new()
		var torus := TorusMesh.new()
		torus.inner_radius = 1.35 + index * 0.34
		torus.outer_radius = torus.inner_radius + 0.018 + index * 0.006
		torus.rings = 96
		torus.ring_segments = 10
		ring.mesh = torus
		var ring_material := StandardMaterial3D.new()
		ring.material_override = ring_material
		add_child(ring)
		_rings.append(ring)
		_ring_materials.append(ring_material)

	_http = HTTPRequest.new()
	_http.timeout = 2.0
	add_child(_http)

	_poll_timer = Timer.new()
	_poll_timer.wait_time = 0.40
	_poll_timer.autostart = true
	add_child(_poll_timer)

	var layer := CanvasLayer.new()
	add_child(layer)
	var title := Label.new()
	title.text = "MARK SCOUT  /  PRESENCE 3D"
	title.position = Vector2(34, 28)
	title.add_theme_font_size_override("font_size", 20)
	title.add_theme_color_override("font_color", Color(0.72, 0.91, 1.0))
	layer.add_child(title)

	_state_label = Label.new()
	_state_label.position = Vector2(34, 630)
	_state_label.add_theme_font_size_override("font_size", 26)
	layer.add_child(_state_label)

	_detail_label = Label.new()
	_detail_label.position = Vector2(34, 670)
	_detail_label.size = Vector2(1180, 42)
	_detail_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	_detail_label.add_theme_font_size_override("font_size", 15)
	_detail_label.add_theme_color_override("font_color", Color(0.62, 0.70, 0.76))
	layer.add_child(_detail_label)
	_update_labels()


func _poll_presence() -> void:
	if _endpoint.is_empty() or _token.is_empty():
		_set_error("El núcleo Mark Scout no está disponible.")
		if _smoke_test:
			_finish_smoke(false)
		return
	if _http.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	var headers := PackedStringArray(["Authorization: Bearer %s" % _token])
	var request_error := _http.request(_endpoint + "/api/voice/presence", headers)
	if request_error != OK:
		_set_error("No se pudo iniciar la consulta local (%s)." % request_error)
		if _smoke_test:
			_finish_smoke(false)


func _on_request_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray,
) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		_set_error("El núcleo respondió con error HTTP %s." % response_code)
		if _smoke_test:
			_finish_smoke(false)
		return
	var payload = JSON.parse_string(body.get_string_from_utf8())
	if not payload is Dictionary or not payload.has("presence"):
		_set_error("Respuesta de presencia inválida.")
		if _smoke_test:
			_finish_smoke(false)
		return
	var presence: Dictionary = payload["presence"]
	_state = str(presence.get("state", "offline"))
	_transcript = str(presence.get("transcript", ""))
	_response = str(presence.get("response", ""))
	_error = str(presence.get("error", ""))
	_update_labels()
	if _smoke_test:
		_finish_smoke(true)


func _set_error(message: String) -> void:
	_state = "error"
	_error = message
	_update_labels()


func _update_materials() -> void:
	var color: Color = STATE_COLORS.get(_state, STATE_COLORS["offline"])
	_core_material.albedo_color = Color(color.r * 0.24, color.g * 0.24, color.b * 0.24, 1.0)
	_core_material.metallic = 0.72
	_core_material.roughness = 0.18
	_core_material.emission_enabled = true
	_core_material.emission = color
	_core_material.emission_energy_multiplier = 1.4 + _state_intensity(_state) * 2.2
	for index in _rings.size():
		var ring_material := _ring_materials[index]
		ring_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		ring_material.albedo_color = color
		ring_material.emission_enabled = true
		ring_material.emission = color
		ring_material.emission_energy_multiplier = 1.1 + index * 0.25


func _update_labels() -> void:
	var color: Color = STATE_COLORS.get(_state, STATE_COLORS["offline"])
	_state_label.text = _state.to_upper()
	_state_label.add_theme_color_override("font_color", color)
	var detail := _error if not _error.is_empty() else (_response if not _response.is_empty() else _transcript)
	_detail_label.text = detail if not detail.is_empty() else "Estado efímero autenticado desde el núcleo local."


func _state_intensity(value: String) -> float:
	return {
		"recording": 0.80,
		"transcribing": 0.60,
		"processing": 0.88,
		"speaking": 1.00,
		"loading": 0.45,
	}.get(value, 0.20)


func _finish_smoke(success: bool) -> void:
	var payload := {
		"ok": success,
		"state": _state,
		"authenticated_loopback": success,
	}
	print("MARK_PRESENCE_SMOKE " + JSON.stringify(payload))
	get_tree().quit(0 if success else 2)
