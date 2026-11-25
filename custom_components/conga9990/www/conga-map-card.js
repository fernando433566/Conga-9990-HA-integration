// Original Home Assistant cards. No external scripts or remote assets.
const congaSelections = new Map();
class CongaMapCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity || !config.map_entity) throw new Error("Indica entity y map_entity");
    if (this.manualToken) this.stopManual();
    if (!["all","map","control","rooms","profiles"].includes(config.section || "all")) throw new Error("Sección desconocida");
    this.config = config;
    if (!this.shadowRoot) this.attachShadow({mode: "open"});
    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block}[hidden]{display:none!important}ha-card{padding:16px}h2{margin:0 0 10px;font-size:20px}
        .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0}
        button,select,input{font:inherit;min-height:40px;border-radius:9px;border:1px solid var(--divider-color);padding:8px;color:var(--primary-text-color);background:var(--card-background-color)}
        button{cursor:pointer}button:disabled{opacity:.45;cursor:default}input{min-width:120px;flex:1}
        svg{width:100%;height:min(45vh,440px);min-height:220px;display:block;background:#061b20;touch-action:none;border-radius:10px}
        image{image-rendering:pixelated}
        .joystick{display:grid;grid-template-columns:repeat(3,64px);gap:7px;justify-content:center;margin:14px 0}
        .joystick button{font-size:23px;touch-action:none;user-select:none}
        .muted{font-size:13px;color:var(--secondary-text-color)}.error{color:var(--error-color);white-space:pre-wrap}
        .rooms{display:flex;gap:12px;flex-wrap:wrap}.rooms label{display:flex;align-items:center;gap:5px}
        .primary{background:var(--primary-color);color:var(--text-primary-color)}
      </style>
      <ha-card><h2>Conga</h2><div class="summary"></div><div class="muted freshness"></div>
        <div class="row"><select class="mode" aria-label="Selección del mapa">
          <option value="view">Ver posición</option><option value="spot">Elegir punto</option>
          <option value="zone">Dibujar rectángulo</option><option value="rooms">Elegir habitaciones</option>
        </select><button class="clear">Borrar selección</button></div>
        <svg role="img" aria-label="Mapa del robot"><image width="100%" height="100%"></image>
          <g class="selection"></g>
          <g class="robot" visibility="hidden" aria-label="Posición de la Conga">
            <circle cx="0" cy="0" r="4.4" fill="#050505" stroke="#e8e4df" stroke-width=".65"></circle>
            <path d="M-3.45-1.1A3.65 3.65 0 0 1 3.45-1.1V1.1A3.65 3.65 0 0 1-3.45 1.1Z" fill="#343336"></path>
            <rect x="-1.25" y="-.25" width="2.5" height="2.25" rx=".75" fill="#989898" stroke="#080808" stroke-width=".38"></rect>
            <rect x="-.42" y="-3.45" width=".84" height="1.7" rx=".42" fill="#242326"></rect>
            <circle class="robot-light" cx="0" cy="-3" r=".28" fill="#49d9ed"></circle>
            <path d="M0-4.25l-.7 1.05h1.4Z" fill="#49d9ed"></path>
          </g>
        </svg><div class="rooms row"></div><div class="row"><button class="clean primary">Limpiar selección</button></div>
        <div class="joystick" aria-label="Control manual">
          <button data-direction="left_forward" aria-label="Avanzar a la izquierda">↖</button>
          <button data-direction="forward" aria-label="Avanzar">↑</button>
          <button data-direction="right_forward" aria-label="Avanzar a la derecha">↗</button>
          <button data-direction="turn_left" aria-label="Girar a la izquierda">↶</button>
          <button class="stop" aria-label="Parar movimiento">■</button>
          <button data-direction="turn_right" aria-label="Girar a la derecha">↷</button>
          <span></span><button data-direction="backward" aria-label="Retroceder">↓</button>
        </div><div class="muted">Mantén pulsada una flecha para mover el robot.</div>
        <div class="row"><select class="profiles" aria-label="Perfil de limpieza"></select><button class="run">Ejecutar perfil</button></div>
        <div class="muted">Ajustes del perfil que vas a guardar</div>
        <div class="row"><select class="pattern" aria-label="Patrón de limpieza del perfil"><option value="auto">Normal</option><option value="thorough">A fondo</option><option value="border">Bordes</option><option value="scrub">Fregado</option><option value="spiral">Espiral</option><option value="square_spiral">Espiral cuadrada</option><option value="quiet">Silenciosa</option></select>
          <select class="fan" aria-label="Potencia"><option value="normal">Potencia normal</option><option value="gentle">Suave</option><option value="strong">Turbo</option><option value="close">Sin aspiración</option></select>
          <select class="water" aria-label="Agua"><option value="close">Sin agua</option><option value="low">Agua: baja</option><option value="middle">Agua: media</option><option value="high">Agua: alta</option></select>
          <input class="repeats" type="number" min="1" max="3" value="1" aria-label="Pasadas" style="max-width:65px;min-width:50px"></div>
        <div class="row"><input class="profile-name" placeholder="Nombre del perfil" maxlength="80" aria-label="Nombre del perfil"><button class="save">Guardar selección</button></div>
        <div class="row"><button class="home">Limpiar toda la casa</button><button class="dock">Volver a la base</button></div>
        <div role="status" class="error"></div>
      </ha-card>`;
    this.zones = []; this.spot = null; this.roomIds = new Set();
    this.q(".mode").onchange = () => { this.renderSelection(); this.publishSelection(); };
    this.q(".clear").onclick = () => { this.zones = []; this.spot = null; this.roomIds.clear(); this.renderRooms(); this.renderSelection(); this.publishSelection(); };
    this.q(".clean").onclick = () => this.clean();
    this.q(".save").onclick = () => this.save();
    this.q(".run").onclick = () => this.call("run_profile", {name: this.q(".profiles").value});
    this.q(".home").onclick = () => this.call("clean_home");
    this.q(".dock").onclick = () => this.haCall("vacuum", "return_to_base");
    this.q(".stop").onclick = () => this.stopManual();
    this.shadowRoot.querySelectorAll("[data-direction]").forEach(button => {
      button.onpointerdown = e => { e.preventDefault(); button.setPointerCapture(e.pointerId); this.move(button.dataset.direction); };
      button.onpointerup = button.onpointercancel = () => this.stopManual();
      button.onlostpointercapture = () => { if (this.manualToken) this.stopManual(); };
      button.onkeydown = e => { if ([" ","Enter"].includes(e.key) && !e.repeat) { e.preventDefault(); this.move(button.dataset.direction); } };
      button.onkeyup = e => { if ([" ","Enter"].includes(e.key)) this.stopManual(); };
    });
    const svg = this.q("svg");
    svg.onpointerdown = e => {
      if (!this.attrs?.map_width || !["spot", "zone"].includes(this.mode)) return;
      e.preventDefault(); svg.setPointerCapture(e.pointerId); this.drag = this.point(e);
      if (this.mode === "spot") { this.spot = this.drag; this.drag = null; this.renderSelection(); this.publishSelection(); }
    };
    svg.onpointerup = e => {
      if (!this.drag) return;
      const end = this.point(e), start = this.drag; this.drag = null;
      if (Math.abs(start[0] - end[0]) < 1 || Math.abs(start[1] - end[1]) < 1) return;
      if (this.zones.length >= 3) return this.error("Selecciona hasta tres rectángulos.");
      const x0 = Math.min(start[0],end[0]), x1 = Math.max(start[0],end[0]);
      const y0 = Math.min(start[1],end[1]), y1 = Math.max(start[1],end[1]);
      this.zones.push([[x0,y0],[x1,y0],[x1,y1],[x0,y1]]); this.renderSelection(); this.publishSelection();
    };
    svg.onpointercancel = () => { this.drag = null; };
    this.applySection();
    this.receiveSelection(congaSelections.get(config.entity));
  }
  applySection() {
    const section = this.config.section || "all";
    const row = selector => this.q(selector).closest(".row");
    const groups = [
      [this.q(".summary"), ["map"]], [this.q(".freshness"), ["map"]],
      [row(".mode"), ["map"]], [this.q("svg"), ["map"]],
      [this.q(".rooms"), ["rooms"]], [row(".clean"), ["map","rooms"]],
      [this.q(".joystick"), ["control"]], [this.q(".joystick").nextElementSibling, ["control"]],
      [row(".home"), ["control"]], [row(".profiles"), ["profiles"]],
      [row(".pattern"), ["profiles"]], [row(".pattern").previousElementSibling, ["profiles"]],
      [row(".profile-name"), ["profiles"]]
    ];
    for (const [node, sections] of groups) node.toggleAttribute("hidden", section !== "all" && !sections.includes(section));
    this.q("h2").textContent = {map:"Mapa y localización",control:"Control de la Conga",rooms:"Habitaciones",profiles:"Perfiles de limpieza",all:"Conga"}[section];
    this.q('.mode option[value="rooms"]').hidden = section === "map";
    if (section === "rooms") this.q(".mode").value = "rooms";
    const hint = document.createElement("div"); hint.className = "muted selection-hint";
    hint.hidden = section !== "profiles";
    hint.textContent = "Elige habitaciones o una zona en las otras tarjetas para guardar un perfil.";
    row(".profiles").before(hint);
  }
  publishSelection() {
    const detail = {entity:this.config.entity, map_id:this.mapId, mode:this.mode,
      rooms:[...this.roomIds], zones:this.zones, spot:this.spot};
    congaSelections.set(detail.entity, detail);
    window.dispatchEvent(new CustomEvent("conga9990-selection", {detail}));
  }
  receiveSelection(detail) {
    if (!detail || !this.config || detail.entity !== this.config.entity) return;
    if (this.mapId !== undefined && detail.map_id !== this.mapId) return;
    this.roomIds = new Set(detail.rooms); this.zones = detail.zones.map(zone => zone.map(point => [...point]));
    this.spot = detail.spot ? [...detail.spot] : null;
    if (this.config.section !== "rooms") this.q(".mode").value = this.config.section === "map" && detail.mode === "rooms" ? "view" : detail.mode;
    this.renderRooms(); this.renderSelection();
    const hint = this.q(".selection-hint");
    if (hint) hint.textContent = detail.mode === "rooms" ? `${detail.rooms.length} habitaciones seleccionadas para guardar el perfil.` : `${detail.zones.length} zonas seleccionadas para guardar el perfil.`;
  }
  q(selector) { return this.shadowRoot.querySelector(selector); }
  get mode() { return this.q(".mode").value; }
  set hass(hass) {
    this._hass = hass;
    if (!this.config) return;
    const vacuum = hass.states[this.config.entity], image = hass.states[this.config.map_entity];
    this.attrs = image?.attributes || {};
    const a = this.attrs;
    if (this.mapId !== undefined && this.mapId !== a.map_id) { this.zones = []; this.spot = null; this.roomIds.clear(); }
    this.mapId = a.map_id;
    this.q(".summary").textContent = `${vacuum?.state || "No disponible"} · Batería: ${vacuum?.attributes.battery_level ?? "—"}%`;
    const fresh = a.position_fresh && a.position_updated && Date.now() - Date.parse(a.position_updated) <= 30000;
    const mapLabel = a.live ? "Mapa en directo" : "Mapa guardado";
    this.q(".freshness").textContent = fresh ? mapLabel + " · posición actualizada" : mapLabel + " · sin posición reciente";
    if (!fresh && a.robot_position) this.q(".freshness").textContent = "Última posición conocida · " + new Date(a.position_updated).toLocaleString();
    if (!a.map_stable) this.q(".freshness").textContent += " · sin división finalizada en habitaciones";
    if (a.map_width && a.map_height) this.q("svg").setAttribute("viewBox", `0 0 ${a.map_width} ${a.map_height}`);
    if (image?.attributes.entity_picture) {
      const href = image.attributes.entity_picture + (image.attributes.entity_picture.includes("?") ? "&" : "?") + "_conga=" + encodeURIComponent(image.state || "");
      if (this.q("image").getAttribute("href") !== href) this.q("image").setAttribute("href",href);
    }
    const robot = this.q(".robot"); robot.setAttribute("visibility", a.robot_position ? "visible" : "hidden");
    this.q(".robot-light").setAttribute("fill",fresh ? "#49d9ed" : "#78909c");
    if (a.robot_position) {
      const angle = Number.isFinite(Number(a.robot_position.angle)) ? Number(a.robot_position.angle) : 0;
      robot.setAttribute("transform",`translate(${a.robot_position.x} ${a.robot_position.y}) rotate(${angle})`);
    }
    const profiles = this.q(".profiles"), previous = profiles.value;
    profiles.replaceChildren();
    for (const name of a.profiles || []) { const option = document.createElement("option"); option.value = name; option.textContent = name; profiles.append(option); }
    if ([...profiles.options].some(o => o.value === previous)) profiles.value = previous;
    this.q(".run").disabled = !profiles.options.length;
    this.q(".clean").disabled = this.q(".save").disabled = !a.map_width;
    this.renderRooms(); this.renderSelection();
  }
  renderRooms() {
    const root = this.q(".rooms"); root.replaceChildren();
    for (const room of this.attrs?.rooms || []) {
      const label = document.createElement("label"), input = document.createElement("input");
      input.type = "checkbox"; input.checked = this.roomIds.has(room.id);
      input.onchange = () => { input.checked ? this.roomIds.add(room.id) : this.roomIds.delete(room.id); this.q(".mode").value = "rooms"; this.publishSelection(); };
      label.append(input, document.createTextNode(room.name)); root.append(label);
    }
  }
  point(event) {
    const matrix = this.q("svg").getScreenCTM();
    const p = new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse());
    return [Math.max(0,Math.min(this.attrs.map_width - 1,p.x)),Math.max(0,Math.min(this.attrs.map_height - 1,p.y))];
  }
  renderSelection() {
    const root = this.q(".selection"); root.replaceChildren();
    for (const zone of this.zones || []) {
      const polygon = document.createElementNS("http://www.w3.org/2000/svg","polygon");
      polygon.setAttribute("points",zone.map(p => p.join(",")).join(" "));
      polygon.setAttribute("fill","#ffb74d66"); polygon.setAttribute("stroke","#ffb74d"); polygon.setAttribute("stroke-width",".6"); root.append(polygon);
    }
    if (this.spot) {
      const circle = document.createElementNS("http://www.w3.org/2000/svg","circle");
      circle.setAttribute("cx",this.spot[0]); circle.setAttribute("cy",this.spot[1]);circle.setAttribute("r","1.5");circle.setAttribute("fill","#ffb74d");root.append(circle);
    }
  }
  async haCall(domain, action, data={}) {
    this.error("");
    try { await this._hass.callService(domain,action,{entity_id:this.config.entity,...data}); return true; }
    catch(error) { this.error(error.message || String(error)); return false; }
  }
  call(action,data={}) { return this.haCall("conga9990",action,data); }
  async clean() {
    if (this.mode === "spot" && this.spot) return this.call("clean_spot",{x:this.spot[0],y:this.spot[1],map_id:this.mapId});
    if (this.mode === "zone" && this.zones.length) return this.call("clean_zones",{zones:this.zones,map_id:this.mapId});
    if (this.mode === "rooms" && this.roomIds.size) return this.call("clean_rooms",{room_ids:[...this.roomIds]});
    this.error("Selecciona un punto, una zona o una habitación.");
  }
  async save() {
    const name = this.q(".profile-name").value.trim();
    if (!name) return this.error("Escribe un nombre para el perfil.");
    const settings = {clean_pattern:this.q(".pattern").value,fan_speed:this.q(".fan").value,
      water_level:this.q(".water").value,repeats:Number(this.q(".repeats").value)};
    if (this.mode === "rooms" && this.roomIds.size) return this.call("save_profile",{name,room_ids:[...this.roomIds],...settings});
    if (this.mode === "zone" && this.zones.length) return this.call("save_profile",{name,zones:this.zones,...settings});
    this.error("Elige habitaciones o dibuja una zona para guardar el perfil.");
  }
  async move(direction) {
    const token = {}; this.manualToken = token;
    while (this.manualToken === token && this.isConnected) {
      if (!await this.call("manual_move",{direction,duration:.3})) break;
    }
    if (this.manualToken === token) this.manualToken = null;
  }
  stopManual() { this.manualToken = null; return this.call("manual_stop"); }
  connectedCallback() {
    this.selectionHandler = event => this.receiveSelection(event.detail);
    window.addEventListener("conga9990-selection",this.selectionHandler);
    this.blurHandler = () => { if (this.manualToken) this.stopManual(); };
    this.visibilityHandler = () => { if (document.hidden && this.manualToken) this.stopManual(); };
    window.addEventListener("blur",this.blurHandler);
    document.addEventListener("visibilitychange",this.visibilityHandler);
  }
  disconnectedCallback() {
    window.removeEventListener("conga9990-selection",this.selectionHandler);
    window.removeEventListener("blur",this.blurHandler);
    document.removeEventListener("visibilitychange",this.visibilityHandler);
    if (this.manualToken) this.stopManual();
  }
  error(message) { this.q(".error").textContent = message; }
  getCardSize() { return this.config?.section === "map" ? 6 : 3; }
  static getStubConfig() { return {entity:"vacuum.conga",map_entity:"image.conga_saved_map"}; }
}
customElements.define("conga-map-card",CongaMapCard);
window.customCards = window.customCards || [];
window.customCards.push({type:"conga-map-card",name:"Conga: mapa y control",description:"Mapa, posición, zonas, habitaciones, perfiles y control manual."});
