// Viventium's one small native program: the mark in the menu bar and its panel, the window that says what is happening
// while she starts or sets up, and (started with --keep, by launchd, when Viventium starts with this Mac) the keeper that
// runs `./vx keep` every two minutes. One file, AppKit only. vx builds it once, as the app "Viventium AI" in your
// Applications folder, and starts it with the project folder. It knows nothing about Viventium's parts: it reads
// `./vx status`, runs `./vx up` / `./vx down`, asks `./vx settings menu` what its panel shows and changes it there, and
// starts a subscription's own sign-in with `./vx subscriptions NAME`, as you would.
//
// Opening the app starts Viventium:
// opened like any app (Applications, Launchpad, Spotlight, the Dock), it starts her when she rests, and sets her up the
// first time, saying only what the moment needs in a small glass window, then opens her page; while she runs, it only
// opens the page. Quit stops her; opening it again starts her. No terminal, ever, after the first command.
//
// The menu bar mark opens a panel with icon controls. The first greeting can point to those controls.
//
// Why an app, and why the keeper lives here: macOS lets no background program read Documents, Desktop or Downloads
// until you allow that program by name. launchd running /bin/bash on ./vx there just fails ("Operation not
// permitted") and nobody is asked; an app is asked for properly, once, and everything it starts is allowed with it.
import AppKit

let given = CommandLine.arguments.count > 1 && !CommandLine.arguments[1].hasPrefix("-") ? CommandLine.arguments[1] : nil
let built = Bundle.main.object(forInfoDictionaryKey: "ViventiumRoot") as? String
let appSource = Bundle.main.object(forInfoDictionaryKey: "ViventiumSource") as? String ?? ""
let packaged = Bundle.main.object(forInfoDictionaryKey: "ViventiumPackaged") as? Bool == true
let home = FileManager.default.homeDirectoryForCurrentUser
let installed = home.appendingPathComponent(".viventium-light", isDirectory: true)
let root = packaged ? installed.path : [given, built].compactMap { $0 }.first {
    FileManager.default.isExecutableFile(atPath: "\($0)/vx")
}
    ?? FileManager.default.currentDirectoryPath
// Opened by a person (Finder, Launchpad, Spotlight, the Dock), not started by vx or launchd: it opens her, then goes.
let opened = given == nil && !CommandLine.arguments.contains(where: { $0.hasPrefix("--") })
let openNote = Notification.Name("ai.viventium.light.open")  // (a running mark is asked to open her: one app, one mark)
let openNoteObject: String? = packaged ? root : nil
let page = "http://localhost:\(ProcessInfo.processInfo.environment["UI_PORT"] ?? "3400")"
let keeping = CommandLine.arguments.contains("--keep")
let privacy = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders")!
// Whether macOS let the keeper in, for the settings page to say (outside the project: it must be writable when blocked).
let keptFile = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Viventium Light/keep.json")
let logs = "\(root)/logs"
func here(_ name: String) -> Bool { FileManager.default.fileExists(atPath: "\(logs)/\(name)") }
// (--act: a click done without a screen; what it would open is printed, and its change is made at once)
let dry = CommandLine.arguments.contains("--act")
func go(_ url: URL) {
    if dry { print("open \(url.absoluteString)") } else { NSWorkspace.shared.open(url) }
}

// -- vx, run as you would run it --

func environment() -> [String: String] {
    var env = ProcessInfo.processInfo.environment.filter { ["HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "LANG", "PATH"].contains($0.key) }
    env["VX_NO_OPEN"] = "1"  // (this app opens the page itself, once she is ready)
    env["VX_FROM_APP"] = "1"  // (vx never restarts this app from under its own start, and says what to do in the app's words)
    if packaged {
        env["HOME"] = home.path
        env["PATH"] = "\(home.path)/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    }
    return env
}

/// Copy the release payload once, without writing into the app bundle or replacing a user's runtime.
func installPackagedRuntime() throws {
    let fm = FileManager.default
    let stamp = installed.appendingPathComponent(".vx-release")
    func matches() -> Bool {
        (try? installed.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink) == false &&
            (try? String(contentsOf: stamp, encoding: .utf8)) == appSource + "\n" &&
            fm.isExecutableFile(atPath: "\(installed.path)/vx")
    }
    if !matches() {
        guard !fm.fileExists(atPath: installed.path),
              let payload = Bundle.main.url(forResource: "Light", withExtension: nil) else {
            throw CocoaError(.fileWriteFileExists)
        }
        let staging = home.appendingPathComponent(".viventium-light-install-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: staging, withIntermediateDirectories: false,
                               attributes: [.posixPermissions: 0o700])
        defer { try? fm.removeItem(at: staging) }
        let copy = staging.appendingPathComponent("Light", isDirectory: true)
        try fm.copyItem(at: payload, to: copy)
        try fm.setAttributes([.posixPermissions: 0o700], ofItemAtPath: copy.path)
        do { try fm.moveItem(at: copy, to: installed) } catch {
            if !matches() { throw error }
        }
    }
    try (Bundle.main.bundleURL.path + "\n").write(
        to: installed.appendingPathComponent(".vx-app"), atomically: true, encoding: .utf8)
}

/// One run of `./vx ARGS` (its answer, and whether it could run at all: 126, or "Operation not permitted", is macOS
/// keeping the folder closed), with `input` on its standard input.
func vx(_ args: [String], input: String? = nil) -> (said: String, code: Int32, allowed: Bool) {
    let run = Process()
    run.executableURL = URL(fileURLWithPath: "/bin/bash")
    run.arguments = ["\(root)/vx"] + args
    run.currentDirectoryURL = URL(fileURLWithPath: root)
    run.environment = environment()
    let out = Pipe(), into = Pipe()
    run.standardOutput = out
    run.standardError = args.first == "status" || args.first == "keep" ? out : FileHandle.nullDevice
    run.standardInput = input == nil ? FileHandle.nullDevice : into
    do { try run.run() } catch { return ("", 127, false) }
    if let input {
        try? into.fileHandleForWriting.write(contentsOf: Data(input.utf8))
        try? into.fileHandleForWriting.close()
    }
    let data = out.fileHandleForReading.readDataToEndOfFile()
    run.waitUntilExit()
    let text = String(data: data, encoding: .utf8) ?? ""
    return (text, run.terminationStatus, !(run.terminationStatus == 126 || text.contains("Operation not permitted")))
}

/// One round of `./vx keep`. False when macOS would not let it read the project folder.
func keep() -> Bool {
    let (said, _, allowed) = vx(["keep"])
    FileHandle.standardOutput.write(said.data(using: .utf8)!)  // (launchd sends it to logs/keep.log)
    let note: [String: Any] = ["blocked": !allowed, "at": Int(Date().timeIntervalSince1970), "root": root,
                               "pid": ProcessInfo.processInfo.processIdentifier, "source": appSource]
    try? FileManager.default.createDirectory(at: keptFile.deletingLastPathComponent(), withIntermediateDirectories: true)
    if let data = try? JSONSerialization.data(withJSONObject: note) { try? data.write(to: keptFile, options: .atomic) }
    return allowed
}

/// `./vx up [PLACE]`, each line it says handed to `line` as it comes, then its exit status to `done` (both on the main
/// thread). Foundation starts it as a process group of its own (its pid is its group's), so a Quit stops the whole of it:
/// its downloads and builds too (stopping()). No place: the one she last ran; the first time, Local or Hybrid by itself.
@discardableResult
func startHer(place: String? = nil, setupInput: Pipe? = nil,
              line: @escaping (String) -> Void, done: @escaping (Int32) -> Void) -> Process {
    let run = Process()
    run.executableURL = URL(fileURLWithPath: "/bin/bash")
    run.arguments = ["\(root)/vx", "up"] + (place.map { [$0] } ?? [])
    run.currentDirectoryURL = URL(fileURLWithPath: root)
    var env = environment()
    if setupInput != nil { env["VX_SETUP_WINDOW"] = "1" }
    run.environment = env
    let out = Pipe()
    run.standardOutput = out
    run.standardError = out
    if let setupInput { run.standardInput = setupInput } else { run.standardInput = FileHandle.nullDevice }
    out.fileHandleForReading.readabilityHandler = { handle in
        let data = handle.availableData
        guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
        for piece in text.split(whereSeparator: { $0 == "\n" || $0 == "\r" }) {
            let said = piece.trimmingCharacters(in: .whitespaces)
            if !said.isEmpty { DispatchQueue.main.async { line(said) } }
        }
    }
    run.terminationHandler = { finished in
        out.fileHandleForReading.readabilityHandler = nil
        DispatchQueue.main.async { done(finished.terminationStatus) }
    }
    do { try run.run() } catch { DispatchQueue.main.async { done(127) } }
    return run
}

/// A start this app made, stopped whole (its process group: vx and what it runs in the foreground). True once it is gone.
@discardableResult
func stopping(_ run: Process?) -> Bool {
    guard let run, run.isRunning else { return true }
    let group = getpgid(run.processIdentifier) == run.processIdentifier ? -run.processIdentifier : run.processIdentifier
    kill(group, SIGTERM)  // (its group: the start and what it runs in the foreground; never this app's own group)
    for _ in 0..<50 where run.isRunning { usleep(100_000) }
    if run.isRunning { kill(group, SIGKILL); usleep(200_000) }
    return !run.isRunning
}

func isUp(_ status: String) -> Bool {
    status.contains("agent: up") && status.contains("ui: up") && !mute(status) && !asking(status) && !awaitingAnswer(status)
}

func awaitingAnswer(_ status: String) -> Bool {
    status.contains("ui: up") && status.split(whereSeparator: \.isNewline).contains {
        $0.trimmingCharacters(in: .whitespaces) == "mind: connected, awaiting first answer"
    }
}
func mindFailure(_ status: String) -> String {
    let prefix = "mind reason: "
    return status.split(whereSeparator: \.isNewline)
        .map { $0.trimmingCharacters(in: .whitespaces) }
        .first { $0.hasPrefix(prefix) }.map { String($0.dropFirst(prefix.count)) } ?? ""
}

func restoreReason(_ status: String) -> String {
    let prefix = "restore reason: "
    return status.split(whereSeparator: \.isNewline).first { $0.hasPrefix(prefix) }
        .map { String($0.dropFirst(prefix.count)) } ?? ""
}

/// Her parts up, but her mind did not answer at the last start (./vx status says so, from logs/blocked): not ready, so
/// opening the app starts her again, which asks her mind again (every process up while her mind could not answer).
func mute(_ status: String) -> Bool {
    status.split(whereSeparator: \.isNewline).contains { $0.trimmingCharacters(in: .whitespaces) == "mind: not answering" }
}
/// Her parts up while a start at work has not written its verdict yet (./vx status, from logs/up.lock and
/// logs/mind-answer): not ready until it says, so the panel never introduces her before it (a clean Mac: "Viventium
/// lives here" opened 15 s before the window said her mind could not answer). She is starting. No start at work: as before.
func asking(_ status: String) -> Bool {
    status.split(whereSeparator: \.isNewline).contains {
        $0.trimmingCharacters(in: .whitespaces) == "mind: not asked yet (a start is at work)"
    }
}

// What `./vx up` says of a part ("  tts: started"), in plain words (never "her": no gender on screen); anything else it
// says is already in plain words.
let partWords = ["stt": "hearing", "tts": "the voice", "agent": "the mind", "ui": "the page", "livekit": "calls",
                 "telegram": "Telegram", "chat": "Telegram", "workers": "the Workers", "xperfect": "the Workers",
                 "life-core": "memory", "life-index": "memory", "embed-model": "memory", "model": "this Mac's model",
                 "worker-model": "this Mac's model", "doorbell": "the clock", "doors": "the phone"]

func plain(_ said: String) -> String {
    let parts = said.split(separator: ":", maxSplits: 1).map { $0.trimmingCharacters(in: .whitespaces) }
    guard parts.count == 2, let words = partWords[parts[0]] else { return said }
    switch parts[1] {
    case let how where how.hasPrefix("building"): return "Getting \(words) ready"
    case let how where how.hasPrefix("started") || how.hasPrefix("ready") || how.hasPrefix("up"): return "Starting \(words)"
    default: return "\(words.prefix(1).uppercased() + words.dropFirst()): \(parts[1])"
    }
}

/// One line of what the app did, in plain words, in logs/app.log (what it opened, started, said; never anything of his).
func note(_ what: String) {
    let line = "\(ISO8601DateFormatter().string(from: Date())) \(what)\n"
    let file = URL(fileURLWithPath: "\(logs)/app.log")
    if let handle = try? FileHandle(forWritingTo: file) {
        handle.seekToEndOfFile()
        handle.write(line.data(using: .utf8)!)
        try? handle.close()
    } else {
        try? line.write(to: file, atomically: true, encoding: .utf8)
    }
}

func freeGB() -> Int {
    // (what df says, as vx measures it: never purgeable space vx does not count, or the window would start her again
    // and again on space vx refuses)
    if let said = ProcessInfo.processInfo.environment["VX_FREE_GB"], let gb = Int(said) { return gb }  // (a test's)
    let values = try? URL(fileURLWithPath: NSHomeDirectory()).resourceValues(forKeys: [.volumeAvailableCapacityKey])
    return (values?.volumeAvailableCapacity ?? 0) / 1_073_741_824
}

// -- How things look (the design language: graphite, no outlines, no warm fill on any control, a crisp mark) --

func tone(_ dark: NSColor, _ light: NSColor) -> NSColor {
    NSColor(name: nil) { $0.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light }
}
func hex(_ value: UInt32, _ alpha: CGFloat = 1) -> NSColor {
    NSColor(srgbRed: CGFloat(value >> 16 & 255) / 255, green: CGFloat(value >> 8 & 255) / 255, blue: CGFloat(value & 255) / 255, alpha: alpha)
}
let ink = tone(hex(0xf7f3ec), hex(0x15171c))  // text
let soft = tone(hex(0xb8bbc2), hex(0x555963))  // a quieter line
let onFill = tone(hex(0xf5f6f8), hex(0x15171c))  // a control that is on: plain white on graphite, ink on pearl
let onInk = tone(hex(0x15171c), hex(0xffffff))
let offFill = tone(NSColor(white: 1, alpha: 0.075), hex(0x15171c, 0.06))
let hoverFill = tone(NSColor(white: 1, alpha: 0.13), hex(0x15171c, 0.11))
let graphite = tone(hex(0x15171b), hex(0xeef0f3))  // (renders only: the glass macOS draws is not in a picture)

// Her mark, traced from the logo (a V whose right stroke is an i), drawn `wide` points across, centred in `box`
// (flipped: y grows downwards).
func drawMark(in box: NSRect, wide: CGFloat, color: NSColor) {
    let shapes: [[(CGFloat, CGFloat)]] = [[(266, 286), (396, 286), (505, 550), (447, 671)],
                                          [(648, 286), (757, 286), (704, 404), (596, 404)],
                                          [(585, 428), (694, 428), (556, 738), (450, 738)]]
    let scale = wide / 491.0
    let left = box.minX + (box.width - 491 * scale) / 2 - 266 * scale, top = box.minY + (box.height - 452 * scale) / 2 - 286 * scale
    color.setFill()
    for shape in shapes {
        let path = NSBezierPath()
        path.move(to: NSPoint(x: left + shape[0].0 * scale, y: top + shape[0].1 * scale))
        for point in shape.dropFirst() { path.line(to: NSPoint(x: left + point.0 * scale, y: top + point.1 * scale)) }
        path.close()
        path.fill()
    }
}

// The mark in the menu bar, as a template image: macOS tints it.
func mark(dim: Bool) -> NSImage {
    let image = NSImage(size: NSSize(width: 18, height: 18), flipped: true) { box in
        drawMark(in: box, wide: 15, color: NSColor.black.withAlphaComponent(dim ? 0.45 : 1))
        return true
    }
    image.isTemplate = true
    return image
}

// The app's icon: her mark, crisp and light, on a graphite tile (the design language: graphite, no outlines, no warm
// fill), with the rounded corners every Mac app icon has.
func icon(side: CGFloat) -> NSImage {
    NSImage(size: NSSize(width: side, height: side), flipped: true) { box in
        let inset = side * 0.1, tile = box.insetBy(dx: inset, dy: inset)
        NSColor(calibratedRed: 0.13, green: 0.135, blue: 0.145, alpha: 1).setFill()
        NSBezierPath(roundedRect: tile, xRadius: tile.width * 0.225, yRadius: tile.width * 0.225).fill()
        drawMark(in: tile, wide: tile.width * 0.62, color: NSColor(calibratedWhite: 0.97, alpha: 1))
        return true
    }
}

/// An icon by name: an SF Symbol, or a provider's own mark from the page's (call/ui/public/marks, drawn in one tone,
/// never its brand colour on a control), or "hybrid": this Mac with a small cloud above it. Template images: tinted when drawn.
func glyph(_ name: String, size: CGFloat) -> NSImage? {
    if name == "hybrid", let mac = glyph("laptopcomputer", size: size), let cloud = glyph("cloud.fill", size: size * 0.62) {
        let made = NSImage(size: NSSize(width: mac.size.width + size * 0.2, height: mac.size.height + size * 0.28), flipped: false) { box in
            mac.draw(in: NSRect(x: 0, y: 0, width: mac.size.width, height: mac.size.height))
            cloud.draw(in: NSRect(x: box.width - cloud.size.width, y: box.height - cloud.size.height,
                                  width: cloud.size.width, height: cloud.size.height))
            return true
        }
        made.isTemplate = true
        return made
    }
    if name.hasPrefix("mark:") {
        guard let image = NSImage(contentsOfFile: "\(root)/call/ui/public/marks/\(name.dropFirst(5)).svg") else { return nil }
        image.size = NSSize(width: size, height: size)
        image.isTemplate = true
        return image
    }
    guard let symbol = NSImage(systemSymbolName: name, accessibilityDescription: nil)?
        .withSymbolConfiguration(NSImage.SymbolConfiguration(pointSize: size, weight: .regular)) else { return nil }
    symbol.isTemplate = true
    return symbol
}

/// A template image drawn in one colour, centred in `box`.
func paint(_ image: NSImage, in box: NSRect, color: NSColor) {
    let size = image.size, at = NSRect(x: box.midX - size.width / 2, y: box.midY - size.height / 2, width: size.width, height: size.height)
    let tinted = NSImage(size: size, flipped: false) { rect in
        image.draw(in: rect)
        color.set()
        rect.fill(using: .sourceAtop)
        return true
    }
    tinted.draw(in: at.integral)
}

// -- What the panel shows (./vx settings menu: settings/service.py menu) --

struct Place { var id = "", name = "", need = "", say = "", plans: [String] = [] }
struct Look {
    var profile = "", applying = "", waitingFor = "", why = "", mindFailure = "", recoveryReason = ""
    var recoveryFailed = false
    var places: [Place] = []
    var open = false, ears = false, mode = "talk", voiceAvailable = true
    var eyesCan = false, eyesOn = false, eyesAdding = false
    var read = false  // (an answer came: before it, nothing is shown that it would decide)

    init() {}
    init(_ json: [String: Any]) {
        read = true
        profile = json["profile"] as? String ?? ""
        let applying = json["applying"] as? [String: Any] ?? [:]
        self.applying = applying["state"] as? String ?? ""
        waitingFor = applying["for"] as? String ?? ""
        why = applying["why"] as? String ?? ""
        places = (json["places"] as? [[String: Any]] ?? []).map {
            Place(id: $0["id"] as? String ?? "", name: $0["name"] as? String ?? "", need: $0["need"] as? String ?? "",
                  say: $0["say"] as? String ?? "", plans: $0["plans"] as? [String] ?? [])
        }
        open = json["open"] as? Bool ?? false
        ears = json["ears"] as? Bool ?? false
        mode = json["mode"] as? String ?? "talk"
        voiceAvailable = json["voice_available"] as? Bool ?? true
        let eyes = json["eyes"] as? [String: Any] ?? [:]
        eyesCan = eyes["can"] as? Bool ?? false
        eyesOn = eyes["on"] as? Bool ?? false
        eyesAdding = eyes["adding"] as? Bool ?? false
    }
}

func parse(_ said: String) -> [String: Any]? {
    guard let data = said.data(using: .utf8), let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
    return json
}

/// The subscriptions this Mac's tools can use, and which are signed in (`./vx subscriptions`: "claude signed-in").
func subscriptions() -> [(id: String, on: Bool)] {
    vx(["subscriptions"]).said.split(separator: "\n").compactMap { line in
        let parts = line.split(separator: " ")
        return parts.count == 2 && planNames[String(parts[0])] != nil ? (String(parts[0]), parts[1] == "signed-in") : nil
    }
}
let planNames = ["claude": "Claude", "codex": "ChatGPT", "grok_mind": "Grok"]
let planMarks = ["claude": "mark:claude", "codex": "mark:openai"]

// -- The parts a surface is made of: drawn, never outlined --

/// A round logo toggle: off (a faint disc), on (lit: white on graphite, ink on pearl), or dim (this Mac cannot yet: it
/// says what it needs when pointed at, and its click leads to what fixes it). Named when pointed at; nothing written.
final class Disc: NSView {
    var on = false { didSet { needsDisplay = true; setAccessibilityValue(on) } }
    var dim = false { didSet { alphaValue = dim ? 0.38 : 1 } }
    var quiet = false  // (the small row: no disc until pointed at)
    var explanation = ""
    var hoverChanged: ((NSView, String?) -> Void)?
    var hovering = false { didSet {
        needsDisplay = true
        hoverChanged?(self, hovering ? explanation : nil)
    } }
    var highlighted = false { didSet { needsDisplay = true } }
    var image: NSImage?
    var tapped: (() -> Void)?
    let side: CGFloat

    init(_ name: String, glyph symbol: String, side: CGFloat = 44, quiet: Bool = false, tapped: @escaping () -> Void) {
        self.side = side
        self.quiet = quiet
        self.tapped = tapped
        image = glyph(symbol, size: quiet ? 13 : 17)
        super.init(frame: NSRect(x: 0, y: 0, width: side, height: side))
        explanation = name
        setAccessibilityElement(true)
        setAccessibilityRole(quiet ? .button : .checkBox)
        setAccessibilityLabel(name)
        translatesAutoresizingMaskIntoConstraints = false
        widthAnchor.constraint(equalToConstant: side).isActive = true
        heightAnchor.constraint(equalToConstant: side).isActive = true
    }
    required init?(coder: NSCoder) { nil }

    override var intrinsicContentSize: NSSize { NSSize(width: side, height: side) }
    override func updateTrackingAreas() {
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(NSTrackingArea(rect: bounds, options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect], owner: self))
    }
    override func mouseEntered(with event: NSEvent) { hovering = true }
    override func mouseExited(with event: NSEvent) { hovering = false }
    override func mouseDown(with event: NSEvent) {}
    override func mouseUp(with event: NSEvent) {
        if bounds.contains(convert(event.locationInWindow, from: nil)) { tapped?() }
    }
    override func accessibilityPerformPress() -> Bool { tapped?(); return true }

    override func draw(_ dirty: NSRect) {
        effectiveAppearance.performAsCurrentDrawingAppearance {
            if highlighted {
                for (outer, inner, opacity) in [(0.0, 1.5, 0.14), (1.5, 3.0, 0.35), (3.0, 4.5, 0.60)] {
                    ink.withAlphaComponent(opacity).setFill()
                    let glow = NSBezierPath(ovalIn: bounds.insetBy(dx: outer, dy: outer))
                    glow.appendOval(in: bounds.insetBy(dx: inner, dy: inner))
                    glow.windingRule = .evenOdd
                    glow.fill()
                }
            }
            let inset: CGFloat = highlighted ? 5 : 1
            let disc = NSBezierPath(ovalIn: bounds.insetBy(dx: inset, dy: inset))
            if on { onFill.setFill(); disc.fill() } else if hovering || highlighted { hoverFill.setFill(); disc.fill() } else if !quiet { offFill.setFill(); disc.fill() }
            if let image { paint(image, in: bounds, color: on ? onInk : quiet && !hovering && !highlighted ? soft : ink) }
        }
    }
}

/// A sign-in: a provider's own mark and its name, on a faint pill; signed in, it is lit and says so with a tick.
final class Pill: NSView {
    var on = false { didSet { needsDisplay = true; width?.constant = intrinsicContentSize.width } }
    var width: NSLayoutConstraint?
    var explanation = ""
    var hoverChanged: ((NSView, String?) -> Void)?
    var hovering = false { didSet {
        needsDisplay = true
        hoverChanged?(self, hovering ? explanation : nil)
    } }
    var button = false  // (the one way forward: ivory with ink, ink with white)
    let title: String, logo: NSImage?
    var tapped: (() -> Void)?

    init(_ title: String, logo: String?, button: Bool = false, tapped: @escaping () -> Void) {
        self.title = title
        self.logo = logo.flatMap { glyph($0, size: 15) }
        self.button = button
        self.tapped = tapped
        super.init(frame: .zero)
        setAccessibilityElement(true)
        setAccessibilityRole(.button)
        setAccessibilityLabel(button ? title : "Sign in to \(title)")
        explanation = button ? title : "Sign in to \(title)"
        translatesAutoresizingMaskIntoConstraints = false
        let size = intrinsicContentSize
        width = widthAnchor.constraint(equalToConstant: size.width)
        width?.isActive = true
        heightAnchor.constraint(equalToConstant: size.height).isActive = true
    }
    required init?(coder: NSCoder) { nil }

    var words: NSAttributedString {
        NSAttributedString(string: title, attributes: [.font: NSFont.systemFont(ofSize: 13, weight: .medium), .foregroundColor: NSColor.black])
    }
    override var intrinsicContentSize: NSSize {
        NSSize(width: ceil(words.size().width) + (logo == nil ? 32 : 54) + (on ? 16 : 0), height: 34)
    }
    override func updateTrackingAreas() {
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(NSTrackingArea(rect: bounds, options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect], owner: self))
    }
    override func mouseEntered(with event: NSEvent) { hovering = true }
    override func mouseExited(with event: NSEvent) { hovering = false }
    override func mouseDown(with event: NSEvent) {}
    override func mouseUp(with event: NSEvent) {
        if bounds.contains(convert(event.locationInWindow, from: nil)) && !on { tapped?() }
    }
    override func accessibilityPerformPress() -> Bool { if !on { tapped?() }; return true }

    override func draw(_ dirty: NSRect) {
        effectiveAppearance.performAsCurrentDrawingAppearance {
            let lit = on || button
            (lit ? onFill : hovering ? hoverFill : offFill).setFill()
            NSBezierPath(roundedRect: bounds, xRadius: bounds.height / 2, yRadius: bounds.height / 2).fill()
            let color = lit ? onInk : ink
            var x: CGFloat = 16
            if let logo {
                paint(logo, in: NSRect(x: x, y: 0, width: 16, height: bounds.height), color: color)
                x += 22
            }
            let text = NSAttributedString(string: title, attributes: [.font: NSFont.systemFont(ofSize: 13, weight: .medium), .foregroundColor: color])
            text.draw(at: NSPoint(x: x, y: (bounds.height - text.size().height) / 2))
            if on, let tick = glyph("checkmark", size: 10) {
                paint(tick, in: NSRect(x: bounds.width - 22, y: 0, width: 12, height: bounds.height), color: color)
            }
        }
    }
}

func label(_ text: String, size: CGFloat, weight: NSFont.Weight = .regular, color: NSColor = ink, wide: CGFloat = 320) -> NSTextField {
    let made = NSTextField(wrappingLabelWithString: text)
    let font = NSFont.systemFont(ofSize: size, weight: weight)
    made.font = font
    made.textColor = color
    made.alignment = .center
    made.isSelectable = false
    // (its size measured here, in its own font, so a line is never cut short by a rounding: one line, or as many as it needs)
    let fits = NSAttributedString(string: text, attributes: [.font: font])
        .boundingRect(with: NSSize(width: wide, height: 1000), options: [.usesLineFragmentOrigin, .usesFontLeading])
    made.translatesAutoresizingMaskIntoConstraints = false
    made.widthAnchor.constraint(equalToConstant: min(wide, ceil(fits.width) + 8)).isActive = true
    made.heightAnchor.constraint(equalToConstant: ceil(fits.height) + 2).isActive = true
    return made
}

func row(_ views: [NSView], spacing: CGFloat = 12) -> NSStackView {
    let made = NSStackView(views: views)
    made.orientation = .horizontal
    made.spacing = spacing
    made.alignment = .centerY
    return made
}

// -- The panel under her mark --

/// What she is doing, as the panel needs it.
enum Now { case ready, connected, starting, resting, blocked, silent, recovery }

/// The panel's controls, built for one moment: her ears, eyes, Wing and Listen only; where she runs; her page,
/// Telegram (with a bot), Settings, Quit. Text only when the moment needs it: the first time, a title of three words;
/// while she is not ready, a word for what she is doing; a dimmed place clicked, the sign-ins that open it.
struct Control {
    let name: String, glyph: String, on: Bool, dim: Bool, say: String, act: String
    var explanation: String {
        if act.hasPrefix("place:") {
            let descriptions = ["place:local": "Use AI only on this Mac", "place:hybrid": "Use this Mac and online AI",
                                "place:cloud": "Use online AI", "place:small-8": "Use online AI with typing",
                                "place:small-16": "Use online AI with local memory", "place:small-24": "Use online AI with local voice"]
            let what = descriptions[act] ?? "Switch to \(name)"
            return dim && !say.isEmpty ? "\(what) · \(say)" : what
        }
        switch act {
        case "ears": return on ? "Turn off the microphone" : "Talk by voice"
        case "eyes": return dim ? "The living face is being added" : on ? "Hide the living face" : "Show the living face"
        case "wing": return on ? "Reply to everything I say" : "Reply only when addressed"
        case "listen": return on ? "Speak replies again" : "Listen without speaking"
        case "page": return name == "Start" ? "Start Viventium AI" : "Open the conversation"
        case "telegram": return "Open your Telegram conversation"
        case "life": return "Open your Life folder"
        case "settings": return "Open Settings"
        case "doctor": return "Check what needs repair"
        case "quit": return "Quit Viventium AI"
        default: return name
        }
    }
}

func controls(_ now: Now, _ look: Look, bot: Bool) -> (her: [Control], places: [Control], small: [Control]) {
    if now == .recovery {
        return ([], [], [
            Control(name: "Settings", glyph: "gearshape", on: false, dim: false, say: "", act: "settings"),
            Control(name: "Doctor", glyph: "stethoscope", on: false, dim: false, say: "", act: "doctor"),
            Control(name: "Quit", glyph: "power", on: false, dim: false, say: "", act: "quit"),
        ])
    }
    let her: [Control] = [
        look.voiceAvailable ? Control(name: "Ears", glyph: "ear", on: now == .ready && look.ears, dim: false, say: "", act: "ears") : nil,
        look.eyesCan ? Control(name: "Eyes", glyph: "eye", on: look.eyesOn, dim: look.eyesAdding, say: look.eyesAdding ? "Being added" : "", act: "eyes") : nil,
        look.voiceAvailable ? Control(name: "Wing", glyph: "bird", on: look.mode == "wing", dim: false, say: "", act: "wing") : nil,
        look.voiceAvailable ? Control(name: "Listen only", glyph: "speaker.slash", on: look.mode == "listen", dim: false, say: "", act: "listen") : nil,
    ].compactMap { $0 }
    let marks = ["local": "lock.laptopcomputer", "hybrid": "hybrid", "cloud": "cloud",
                 "small-8": "cloud", "small-16": "hybrid", "small-24": "hybrid"]
    let places = look.places.map {
        Control(name: $0.need.isEmpty ? $0.name : "\($0.name) · \($0.say)", glyph: marks[$0.id] ?? "circle", on: $0.id == look.profile,
                dim: !$0.need.isEmpty, say: $0.say, act: "place:\($0.id)")
    }
    let small: [Control] = [
        Control(name: now == .resting || now == .silent ? "Start" : "Conversation", glyph: now == .resting || now == .silent ? "play.fill" : "bubble.left",
                on: false, dim: false, say: "", act: "page"),
        bot && now == .ready ? Control(name: "Telegram", glyph: "paperplane", on: false, dim: false, say: "", act: "telegram") : nil,
        Control(name: "Life folder", glyph: "folder", on: false, dim: false, say: "", act: "life"),
        Control(name: "Settings", glyph: "gearshape", on: false, dim: false, say: "", act: "settings"),
        Control(name: "Quit", glyph: "power", on: false, dim: false, say: "", act: "quit"),
    ].compactMap { $0 }
    return (her, places, small)
}

/// The one line the panel writes, only when the moment needs it ("" when she is ready and nothing waits).
func stateLine(_ now: Now, _ look: Look) -> String {
    switch now {
    case .blocked: return "macOS is not letting Viventium start"
    case .starting: return "Starting"
    case .resting: return "Resting"
    case .connected: return "ChatGPT connected. Waiting for the first answer."
    case .silent: return look.mindFailure.isEmpty ? "Viventium's mind is not answering" : look.mindFailure
    case .recovery: return look.recoveryReason
    case .ready: break
    }
    switch look.applying {
    case "restarting": return "Switching"
    case "waiting" where look.waitingFor == "call": return "Switches after this call"
    case "waiting" where look.waitingFor == "work": return "Switches when the work is done"
    case "failed": return look.why
    default: return ""
    }
}

final class Panel: NSView {
    let stack = NSStackView()
    var act: ((String) -> Void)?
    let caption = NSTextField(wrappingLabelWithString: "")
    weak var hoverOwner: NSView?

    func explain(_ owner: NSView, _ text: String?) {
        if let text {
            hoverOwner = owner
            caption.stringValue = text
        } else if hoverOwner === owner {
            clearExplanation()
        }
    }

    func clearExplanation() {
        hoverOwner = nil
        caption.stringValue = ""
    }

    override init(frame: NSRect) {
        super.init(frame: frame)
        caption.font = NSFont.systemFont(ofSize: 12)
        caption.textColor = soft
        caption.alignment = .center
        caption.isSelectable = false
        caption.translatesAutoresizingMaskIntoConstraints = false
        caption.widthAnchor.constraint(equalToConstant: 212).isActive = true
        caption.heightAnchor.constraint(equalToConstant: 32).isActive = true
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 14
        stack.edgeInsets = NSEdgeInsets(top: 18, left: 16, bottom: 14, right: 16)
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo: leadingAnchor), stack.trailingAnchor.constraint(equalTo: trailingAnchor),
                                     stack.topAnchor.constraint(equalTo: topAnchor), stack.bottomAnchor.constraint(equalTo: bottomAnchor),
                                     widthAnchor.constraint(equalToConstant: 244)])
    }
    required init?(coder: NSCoder) { nil }

    /// Built again for this moment. `note`: why a change did not happen;
    /// `signIns`: a dimmed place was clicked, its sign-ins (and which are signed in).
    func show(_ now: Now, _ look: Look, note: String = "", signIns: [(id: String, on: Bool)] = [],
              bot: Bool = false, highlight: String? = nil) {
        clearExplanation()
        stack.arrangedSubviews.forEach { $0.removeFromSuperview() }
        let said = note.isEmpty ? stateLine(now, look) : note
        if !said.isEmpty { stack.addArrangedSubview(label(said, size: 12, color: soft, wide: 212)) }
        if now == .blocked {
            let allow = Pill("Allow it in System Settings", logo: nil, button: true) { [weak self] in self?.act?("privacy") }
            allow.hoverChanged = { [weak self] in self?.explain($0, $1) }
            stack.addArrangedSubview(allow)
        } else {
            let (her, places, small) = controls(now, look, bot: bot)
            let disc = { (c: Control, quiet: Bool) -> Disc in
                let made = Disc(c.name, glyph: c.glyph, side: quiet ? 30 : 44, quiet: quiet) { [weak self] in self?.act?(c.act) }
                made.explanation = c.explanation
                made.hoverChanged = { [weak self] in self?.explain($0, $1) }
                made.on = c.on
                made.dim = c.dim
                made.highlighted = c.act == highlight
                return made
            }
            if !her.isEmpty { stack.addArrangedSubview(row(her.map { disc($0, false) })) }
            if look.read && !places.isEmpty { stack.addArrangedSubview(row(places.map { disc($0, false) })) }
            if !signIns.isEmpty {
                stack.addArrangedSubview(row(signIns.map { plan in
                    let pill = Pill(planNames[plan.id] ?? plan.id, logo: planMarks[plan.id]) { [weak self] in self?.act?("signin:\(plan.id)") }
                    pill.on = plan.on
                    pill.explanation = plan.on ? "\(pill.title) is connected" : "Sign in to \(pill.title)"
                    pill.hoverChanged = { [weak self] in self?.explain($0, $1) }
                    return pill
                }, spacing: 8))
            }
            stack.addArrangedSubview(row(small.map { disc($0, true) }, spacing: 8))
        }
        stack.addArrangedSubview(caption)
        layoutSubtreeIfNeeded()
        // Refresh replaces the controls. Restore the caption under a stationary pointer.
        if let window, window.isVisible {
            let point = convert(window.mouseLocationOutsideOfEventStream, from: nil)
            if let disc = hitTest(point) as? Disc { disc.hovering = true }
            if let pill = hitTest(point) as? Pill { pill.hovering = true }
        }
    }
}

// -- The window: what is happening while she starts or sets up, in a few words --

/// One moment of her start: busy or stopped with its one way forward.
struct SetupAccount: Decodable, Equatable {
    let id: String
    let product: String
    let mark: String
    let connect: String
    let key: String
    let background: Bool
    var installed: Bool?
    var signedIn: Bool?
    var keySaved: Bool?
    var signingIn: Bool?
    var outcome: String?
    var roles: String?
    var privacy: String?
}

func setupAccounts(_ data: Data?) -> [SetupAccount]? {
    guard let data else { return nil }
    return try? JSONDecoder().decode([SetupAccount].self, from: data)
}

enum Installer: String {
    case tools

    var bundleID: String {
        switch self {
        case .tools: return "com.apple.installer"
        }
    }
}

enum Moment: Equatable {
    case opening, starting, accounts, chip, privacy
    case installing(Installer, retry: Bool)
    case disk(need: Int)
    case offline(left: Int)
    case downloadPaused
    case mind(said: String, again: Bool)
    case failed(said: String)
    case recovery(said: String)
    case recoverySettings(said: String, copies: [RestoreCopy])
    case recoveryDoctor(said: String)
    case repairing(said: String)
}

struct RestoreCopy: Decodable, Equatable {
    let name: String
    let made: String
}

func words(_ moment: Moment) -> (title: String, detail: String?) {
    switch moment {
    case .opening, .starting: return ("", nil)
    case .accounts: return ("Connect your AI", "Add more anytime in Settings.")
    case .installing(.tools, false): return ("Installing system tools", "Continue in macOS Installer.")
    case .installing(.tools, true): return ("System tools still needed", nil)
    case .disk(let need): return ("Not enough space", "Free up \(max(1, need - freeGB())) GB. Viventium goes on by itself.")
    case .chip: return ("Viventium needs a newer Mac", "One with Apple silicon (M1 or later).")
    case .offline: return ("This Mac is not online", "Viventium goes on by itself once it is.")
    case .downloadPaused: return ("Download paused. Retrying…", nil)
    case .mind(let said, _): return ("Viventium’s mind did not answer", said.isEmpty ? nil : said)
    case .failed(let said): return ("Viventium did not start", said.isEmpty ? "Setup could not finish. Try again." : said)
    case .recovery(let said): return ("Restore needs help", said)
    case .recoverySettings(let said, _): return ("Settings · Backups", said)
    case .recoveryDoctor(let said): return ("Doctor · Restore paused", said)
    case .repairing(let said): return (said, nil)
    case .privacy: return ("macOS is not letting Viventium open its folder",
                           "Allow Viventium AI in System Settings, Privacy and Security, Files and Folders.")
    }
}

final class ActionButton: NSButton {
    private let run: () -> Void

    init(_ title: String, primary: Bool = false, quiet: Bool = false, run: @escaping () -> Void) {
        self.run = run
        super.init(frame: .zero)
        self.title = title
        target = self
        action = #selector(pressed)
        isBordered = false
        attributedTitle = NSAttributedString(string: title, attributes: [
            .font: NSFont.systemFont(ofSize: 13, weight: .medium),
            .foregroundColor: primary ? NSColor.black : quiet ? soft : NSColor.white,
        ])
        wantsLayer = true
        layer?.cornerRadius = 14
        layer?.backgroundColor = primary ? NSColor(white: 0.96, alpha: 1).cgColor : nil
        translatesAutoresizingMaskIntoConstraints = false
        widthAnchor.constraint(equalToConstant: intrinsicContentSize.width + 24).isActive = true
        heightAnchor.constraint(equalToConstant: 29).isActive = true
    }
    required init?(coder: NSCoder) { nil }
    @objc private func pressed() { run() }
}

final class Face: NSView {
    let stack = NSStackView()
    private var fraction: CGFloat = 0
    private var progressTimer: Timer?
    private var showProgress = false
    var act: ((String) -> Void)?
    var submitKey: ((String, String) -> Void)?
    private var keyField: NSSecureTextField?
    private var keyName: String?

    override init(frame: NSRect) {
        super.init(frame: frame)
        appearance = NSAppearance(named: .darkAqua)
        wantsLayer = true
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 9
        stack.edgeInsets = NSEdgeInsets(top: 34, left: 25, bottom: 24, right: 25)
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: leadingAnchor), stack.trailingAnchor.constraint(equalTo: trailingAnchor),
            stack.topAnchor.constraint(equalTo: topAnchor), stack.bottomAnchor.constraint(equalTo: bottomAnchor),
            widthAnchor.constraint(equalToConstant: 460),
        ])
    }
    required init?(coder: NSCoder) { nil }

    func advance(_ target: CGFloat) {
        progressTimer?.invalidate()
        guard window != nil, !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion else {
            fraction = target
            needsDisplay = true
            return
        }
        let start = fraction
        let began = Date()
        progressTimer = Timer.scheduledTimer(withTimeInterval: 1.0 / 60, repeats: true) { [weak self] timer in
            guard let self else { timer.invalidate(); return }
            let elapsed = min(1, Date().timeIntervalSince(began) / 0.28)
            self.fraction = start + (target - start) * (1 - pow(1 - elapsed, 2))
            self.needsDisplay = true
            if elapsed == 1 { timer.invalidate() }
        }
    }

    override func draw(_ dirtyRect: NSRect) {
        guard showProgress else { return }
        let track = NSRect(x: 20, y: 7, width: max(0, bounds.width - 40), height: 2)
        NSColor(white: 1, alpha: 0.1).setFill()
        NSBezierPath(roundedRect: track, xRadius: 1, yRadius: 1).fill()
        NSColor(white: 0.96, alpha: 0.82).setFill()
        var fill = track
        fill.size.width *= fraction
        NSBezierPath(roundedRect: fill, xRadius: 1, yRadius: 1).fill()
    }

    func show(_ moment: Moment, accounts: [SetupAccount] = [], local: Bool = false,
              pending: Set<String> = [], errors: [String: String] = [:], key: String? = nil,
              chatgptConsent: Bool = false, waiting: Bool = false) {
        let sameField = key != nil && key == keyName
        if !sameField { keyField = nil }
        keyName = key
        stack.arrangedSubviews.forEach { stack.removeArrangedSubview($0); $0.removeFromSuperview() }
        let mark = MarkView()
        stack.addArrangedSubview(mark)
        stack.setCustomSpacing(12, after: mark)
        let (title, detail) = words(moment)
        if !title.isEmpty { stack.addArrangedSubview(label(title, size: 23, weight: .semibold, wide: 380)) }
        if let detail { stack.addArrangedSubview(label(detail, size: 13, color: soft, wide: 380)) }
        showProgress = waiting
        needsDisplay = true
        switch moment {
        case .accounts:
            let list = NSStackView()
            list.orientation = .vertical
            list.alignment = .width
            list.spacing = 5
            list.widthAnchor.constraint(equalToConstant: 404).isActive = true
            for account in accounts {
                if chatgptConsent, account.connect == "chatgpt_mind", let notice = account.privacy {
                    list.addArrangedSubview(accountCell(account.product, symbol: "mark:\(account.mark)",
                                                        detail: account.roles, controls: []))
                    list.addArrangedSubview(chatgptChoice(notice))
                } else {
                    list.addArrangedSubview(accountRow(account, pending: pending.contains(account.id), error: errors[account.id]))
                }
                if !account.key.isEmpty && key == account.key && account.keySaved != true {
                    list.addArrangedSubview(secureInput(account))
                }
            }
            if local {
                list.addArrangedSubview(accountCell("This Mac", symbol: "laptopcomputer", detail: nil, controls: []))
            }
            if let message = errors["setup"] {
                list.addArrangedSubview(label(message, size: 12, color: soft, wide: 400))
                list.addArrangedSubview(ActionButton("Try again") { [weak self] in self?.act?("again") })
            } else if !local && !accounts.contains(where: { $0.keySaved == true || (!$0.background && $0.signedIn == true) }) {
                list.addArrangedSubview(label("Connect a mind or add an API key to start.", size: 12, color: soft, wide: 400))
            }
            if let preceding = stack.arrangedSubviews.last { stack.setCustomSpacing(18, after: preceding) }
            stack.addArrangedSubview(list)
        case .installing(let installer, true): action("Try again", installer.rawValue)
        case .failed: action("Try again", "again")
        case .recovery:
            action("Choose backup", "settings")
            stack.addArrangedSubview(row([
                ActionButton("Try again", quiet: true) { [weak self] in self?.act?("again") },
                ActionButton("Doctor", quiet: true) { [weak self] in self?.act?("doctor") },
            ]))
        case .recoverySettings(_, let copies):
            if !copies.isEmpty {
                let picker = NSPopUpButton(frame: .zero, pullsDown: false)
                picker.setAccessibilityLabel("Backup to restore")
                picker.translatesAutoresizingMaskIntoConstraints = false
                picker.widthAnchor.constraint(equalToConstant: 380).isActive = true
                for (index, copy) in copies.enumerated() {
                    picker.addItem(withTitle: "\(copy.made) · \(index + 1)")
                    picker.lastItem?.representedObject = copy.name
                }
                stack.addArrangedSubview(picker)
                stack.addArrangedSubview(label("Current files are backed up first.", size: 12, color: soft, wide: 380))
                stack.addArrangedSubview(ActionButton("Restore backup", primary: true) { [weak self] in
                    if let name = picker.selectedItem?.representedObject as? String { self?.act?("restore:\(name)") }
                })
            } else {
                stack.addArrangedSubview(label("No checked backup is available. Keep the current files before repairing a backup.",
                                               size: 12, color: soft, wide: 380))
            }
            stack.addArrangedSubview(row([
                ActionButton("Back up current files", quiet: true) { [weak self] in self?.act?("backup-current") },
                ActionButton("Doctor", quiet: true) { [weak self] in self?.act?("doctor") },
            ]))
        case .recoveryDoctor: action("Back to Settings", "settings")
        case .mind(_, let again): action(again ? "Try again" : "Choose another mind", again ? "again" : "mind")
        case .privacy: action("Open System Settings", "privacy")
        default: break
        }
        layoutSubtreeIfNeeded()
    }

    private func chatgptChoice(_ notice: String) -> NSView {
        let choice = NSStackView()
        choice.orientation = .vertical
        choice.alignment = .leading
        choice.spacing = 6
        choice.addArrangedSubview(label(notice, size: 12, color: soft, wide: 390))
        choice.addArrangedSubview(row([
            ActionButton("Continue with ChatGPT") { [weak self] in
                self?.act?("chatgpt-connect")
            },
            ActionButton("Cancel", quiet: true) { [weak self] in self?.act?("chatgpt-cancel") },
        ], spacing: 6))
        return choice
    }

    private func accountRow(_ account: SetupAccount, pending: Bool, error: String?) -> NSView {
        var actions = [NSView]()
        if account.signedIn == true { actions.append(confirmed("Subscription")) }
        if account.keySaved == true { actions.append(confirmed("API key")) }
        if actions.isEmpty {
            if pending || account.signingIn == true {
                actions.append(label(account.installed == true ? "Finish in browser" : "Getting ready", size: 12, color: soft, wide: 115))
                if account.connect == "chatgpt_mind" && account.signingIn == true {
                    actions.append(ActionButton("Cancel", quiet: true) { [weak self] in self?.act?("chatgpt-stop") })
                }
            } else {
                let connect = ActionButton(error == nil ? "Connect" : "Retry") { [weak self] in self?.act?("signin:\(account.connect)") }
                connect.setAccessibilityLabel("Connect \(account.product)")
                actions.append(connect)
            }
            if !account.key.isEmpty && keyName != account.key {
                let api = ActionButton("or API key", quiet: true) { [weak self] in self?.act?("key:\(account.key)") }
                api.setAccessibilityLabel("\(account.product) API key")
                actions.append(api)
            }
        }
        return accountCell(account.product, symbol: "mark:\(account.mark)",
                           detail: error ?? account.roles ?? (account.background && account.keySaved != true ? "Background work" : nil),
                           controls: actions)
    }

    private func confirmed(_ title: String) -> NSView {
        let image = NSImageView(image: glyph("checkmark", size: 10) ?? NSImage())
        image.contentTintColor = .white
        return row([image, label(title, size: 12, color: .white, wide: 90)], spacing: 5)
    }

    private func accountCell(_ name: String, symbol: String, detail: String?, controls: [NSView]) -> NSView {
        let image = NSImageView(image: glyph(symbol, size: 17) ?? glyph("circle", size: 17) ?? NSImage())
        image.contentTintColor = .white
        image.widthAnchor.constraint(equalToConstant: 26).isActive = true
        let names = NSStackView()
        names.orientation = .vertical
        names.alignment = .leading
        names.spacing = 2
        let nameLabel = label(name, size: 14, weight: .medium, wide: 174)
        nameLabel.alignment = .left
        names.addArrangedSubview(nameLabel)
        if let detail {
            let hint = label(detail, size: 11, color: soft, wide: 174)
            hint.alignment = .left
            names.addArrangedSubview(hint)
        }
        let spacer = NSView()
        spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        let cell = row([image, names, spacer] + controls, spacing: 5)
        cell.edgeInsets = NSEdgeInsets(top: 4, left: 10, bottom: 4, right: 6)
        cell.heightAnchor.constraint(greaterThanOrEqualToConstant: 48).isActive = true
        return cell
    }

    private func secureInput(_ account: SetupAccount) -> NSView {
        let field = keyField ?? NSSecureTextField()
        if keyField == nil {
            field.setAccessibilityLabel("\(account.product) API key")
            field.placeholderString = "Paste API key"
            field.isBordered = false
            field.focusRingType = .none
            field.drawsBackground = true
            field.backgroundColor = offFill
            field.wantsLayer = true
            field.layer?.cornerRadius = 6
            field.layer?.masksToBounds = true
            field.heightAnchor.constraint(equalToConstant: 26).isActive = true
            field.target = self
            field.action = #selector(sendKey)
            keyField = field
        }
        return row([field, ActionButton("Save", primary: true) { [weak self] in self?.sendKey() },
                    ActionButton("Cancel") { [weak self] in self?.act?("key-cancel") }], spacing: 6)
    }

    func focusKey() { if let keyField { window?.makeFirstResponder(keyField) } }

    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        if let editor = keyField?.currentEditor(), event.charactersIgnoringModifiers == "v",
           event.modifierFlags.intersection(.deviceIndependentFlagsMask) == .command {
            editor.paste(nil)
            return true
        }
        return super.performKeyEquivalent(with: event)
    }

    @objc private func sendKey() {
        guard let keyField, let keyName else { return }
        let value = keyField.currentEditor()?.string ?? keyField.stringValue
        keyField.stringValue = ""
        submitKey?(keyName, value)
    }

    private func action(_ title: String, _ what: String) {
        stack.setCustomSpacing(16, after: stack.arrangedSubviews.last!)
        stack.addArrangedSubview(ActionButton(title, primary: true) { [weak self] in self?.act?(what) })
    }
}

final class MarkView: NSView {
    override init(frame: NSRect) {
        super.init(frame: NSRect(x: 0, y: 0, width: 48, height: 48))
        translatesAutoresizingMaskIntoConstraints = false
        widthAnchor.constraint(equalToConstant: 48).isActive = true
        heightAnchor.constraint(equalToConstant: 48).isActive = true
    }
    required init?(coder: NSCoder) { nil }
    override var isFlipped: Bool { true }
    override func draw(_ dirty: NSRect) {
        effectiveAppearance.performAsCurrentDrawingAppearance { drawMark(in: bounds, wide: 44, color: ink) }
    }
}

/// The window's surface: liquid glass on macOS 26 (NSGlassEffectView), the system's own translucent material before it.
func glass(around content: NSView) -> NSView {
    #if compiler(>=6.2)  // (NSGlassEffectView is in the macOS 26 SDK, which comes with Swift 6.2: an older toolchain builds the rest)
    if #available(macOS 26.0, *) {
        let made = NSGlassEffectView()
        made.cornerRadius = 26
        made.tintColor = NSColor(srgbRed: 0.085, green: 0.09, blue: 0.105, alpha: 0.88)
        made.contentView = content
        return made
    }
    #endif
    let made = NSVisualEffectView()
    made.material = .hudWindow
    made.blendingMode = .behindWindow
    made.state = .active
    content.translatesAutoresizingMaskIntoConstraints = false
    made.addSubview(content)
    NSLayoutConstraint.activate([content.leadingAnchor.constraint(equalTo: made.leadingAnchor), content.trailingAnchor.constraint(equalTo: made.trailingAnchor),
                                 content.topAnchor.constraint(equalTo: made.topAnchor), content.bottomAnchor.constraint(equalTo: made.bottomAnchor)])
    return made
}

// -- The app --

final class Bar: NSObject, NSApplicationDelegate, NSPopoverDelegate, NSWindowDelegate {
    var item: NSStatusItem?
    let popover = NSPopover()
    let panel = Panel(frame: .zero)
    var look = Look()
    var up = false, starting: Date?, blocked = false, silent = false
    var pending = false  // (her parts up, a start at work not yet heard her mind: asking())
    var connected = false
    var window: NSWindow?
    let face = Face(frame: .zero)
    var moment: Moment = .opening
    var tourRequest: String?
    var highlight: String?
    var highlightUntil: TimeInterval = 0
    var tourOpened = false
    var accounts = [SetupAccount]()
    var pendingAccounts = Set<String>()
    var queuedAccounts = Set<String>()
    var accountErrors = [String: String]()
    var editingKey: String?
    var chatgptConsent = false
    var firstWindow = false
    var statusInFlight = false
    var progress: CGFloat = 0
    var didAnswer: Bool {
        !silent && !pending &&
            (try? String(contentsOfFile: "\(logs)/mind-answer", encoding: .utf8))?.split(separator: "\n").first == "answered"
    }
    var canRunLocal: Bool {
        #if arch(arm64)
        ProcessInfo.processInfo.physicalMemory >= 32 * 1024 * 1024 * 1024
        #else
        false
        #endif
    }
    var plans: [(id: String, on: Bool)] = []  // (the window's and the panel's sign-ins)
    /// A dimmed place clicked: its sign-ins shown, and kept (logs/menubar.asked) through the panel closing, so once a
    /// sign-in makes it possible she switches to it by herself. Let go after ten minutes.
    var asked: String? {
        get {
            guard let data = FileManager.default.contents(atPath: "\(logs)/menubar.asked"),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let place = json["place"] as? String, let at = json["at"] as? Double,
                  Date().timeIntervalSince1970 - at < 600 else { return nil }
            return place
        }
        set {
            let file = "\(logs)/menubar.asked"
            if let place = newValue {
                let json = try! JSONSerialization.data(withJSONObject: ["place": place, "at": Date().timeIntervalSince1970])
                FileManager.default.createFile(atPath: file, contents: json)
            } else {
                try? FileManager.default.removeItem(atPath: file)
            }
        }
    }
    var shownForCheck = false  // (--act: the panel as if open)
    var quietForCheck = false  // (--stop-dry: the window's moment, never a window)
    var shown: Bool { popover.isShown || shownForCheck }
    var starter: Process?  // (the start this app made: Quit stops it whole)
    var setupInput: Pipe?
    var offlineTries = 0
    var told = ""  // (why a change from the panel did not happen, shown until the next look)
    var outside: Any?
    var watching: Timer?  // (a stop the window waits out: space freed, a sign-in made)
    var installer: Installer?
    var repairing = false

    @objc func about() {
        NSApp.orderFrontStandardAboutPanel(options: [
            .applicationName: "Viventium AI"])
    }

    func applicationMenu() {
        let menu = NSMenu(title: "Viventium AI")
        let appMenu = NSMenu(title: "Viventium AI")
        let item = NSMenuItem()
        item.submenu = appMenu
        menu.addItem(item)
        let aboutItem = NSMenuItem(title: "About Viventium AI", action: #selector(about), keyEquivalent: "")
        aboutItem.target = self
        appMenu.addItem(aboutItem)
        appMenu.addItem(.separator())
        let quitItem = NSMenuItem(title: "Quit Viventium AI", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        quitItem.target = NSApp
        appMenu.addItem(quitItem)
        NSApp.mainMenu = menu
    }

    func applicationDidFinishLaunching(_ note: Notification) {
        applicationMenu()
        panel.act = { [weak self] in self?.act($0) }
        face.act = { [weak self] in self?.act($0) }
        let holder = NSViewController()
        holder.view = panel
        popover.contentViewController = holder
        popover.behavior = .transient
        popover.delegate = self
        // Opened again by a person while this runs (the Dock, Launchpad, Spotlight): her page, or her start.
        DistributedNotificationCenter.default().addObserver(forName: openNote, object: openNoteObject, queue: .main) { note in
            if note.object as? String == openNoteObject { self.openAsked() }
        }
        place()
        if opened { opening() } else { refresh() }
        Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { _ in
            if self.firstWindow { self.readAccounts() }
        }
        Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { _ in self.followTour() }
        Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { _ in self.refresh() }
        guard keeping else { return }
        let round = {
            DispatchQueue.global().async {
                let allowed = keep()
                DispatchQueue.main.async { self.blocked = !allowed; self.refresh() }
            }
        }
        round()
        Timer.scheduledTimer(withTimeInterval: 120, repeats: true) { _ in round() }
    }

    // Her mark is there whenever she runs, unless switched off in Settings (logs/menubar.off), and always while
    // macOS is blocking the keeper: then it is the one place that says so and leads to the fix.
    func place() {
        let wanted = blocked || !here("menubar.off")
        if wanted, item == nil {
            item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
            item?.button?.toolTip = "Viventium AI"
            item?.button?.target = self
            item?.button?.action = #selector(clicked)
            item?.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])
        } else if !wanted, let shown = item {
            popover.performClose(nil)
            NSStatusBar.system.removeStatusItem(shown)
            item = nil
        }
    }

    // Her Telegram bot's own page, when a bot is connected (its name is kept by the settings package).
    func bot() -> URL? {
        guard let data = FileManager.default.contents(atPath: "\(logs)/telegram-bot.json"),
              let found = try? JSONSerialization.jsonObject(with: data) as? [String: String],
              let name = found["bot"]?.trimmingCharacters(in: CharacterSet(charactersIn: "@")), !name.isEmpty else { return nil }
        return URL(string: "https://t.me/\(name)")
    }

    var now: Now {
        blocked ? .blocked : !look.recoveryReason.isEmpty ? .recovery : up ? .ready : starting != nil || pending ? .starting :
            connected ? .connected : silent ? .silent : .resting
    }

    func refresh() {
        DispatchQueue.global().async {
            let status = vx(["status"]).said
            DispatchQueue.main.async { self.show(status) }
        }
    }

    func show(_ status: String) {  // what `./vx status` says, as the mark and its panel show it
        place()
        if !blocked {
            up = isUp(status)
            silent = mute(status)
            look.mindFailure = mindFailure(status)
            look.recoveryReason = restoreReason(status)
            look.recoveryFailed = status.contains("restore blocked: yes")
            pending = asking(status)
            connected = awaitingAnswer(status)
        }
        item?.button?.image = mark(dim: !up)
        tick()
    }

    /// Every look at her (five seconds): while the panel is open, or a place asked for waits on a sign-in, what the panel
    /// shows is asked again, never a copy redrawn ("Switches after this call" stayed after it switched).
    func tick() {
        if shown || asked != nil { read() }
    }

    func followTour() {
        let now = Date().timeIntervalSince1970
        let data = FileManager.default.contents(atPath: "\(root)/state/core/asks/control.json")
        if up, item != nil,
           let data,
           let cue = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let id = cue["id"] as? String, id != tourRequest,
           let at = cue["at"] as? Double, (0..<3).contains(now - at),
           let name = cue["control"] as? String {
            tourRequest = id
            highlight = name
            highlightUntil = now + 30
            if popover.isShown {
                draw()
            } else {
                open(forTour: true)
            }
            note("tour highlighted \(name)")
        } else if highlight != nil && (data == nil || now >= highlightUntil) {
            highlight = nil
            if tourOpened { popover.performClose(nil) } else if popover.isShown { draw() }
        }
    }

    func draw() {
        panel.show(now, look, note: told, signIns: asked == nil ? [] : plans.filter { plan in
            look.places.first { $0.id == asked }?.plans.contains(plan.id) ?? false
        }, bot: bot() != nil, highlight: highlight)
        popover.contentSize = panel.fittingSize
    }

    @objc func clicked() {
        if popover.isShown { popover.performClose(nil) } else { open() }
    }

    func open(forTour: Bool = false) {
        guard let button = item?.button else { return }
        tourOpened = forTour
        popover.behavior = forTour ? .applicationDefined : .transient
        draw()
        if !forTour { NSApp.activate(ignoringOtherApps: true) }
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        if !forTour { popover.contentViewController?.view.window?.makeKey() }
        outside = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            self?.popover.performClose(nil)
        }
        read()
    }

    func popoverDidClose(_ notification: Notification) {
        panel.clearExplanation()
        if let outside { NSEvent.removeMonitor(outside) }
        outside = nil
        told = ""
        highlight = nil
        tourOpened = false
    }

    /// What the panel shows, asked again (./vx settings menu); then, if a dimmed place was clicked and can run now, she
    /// switches to it.
    func read() {
        let waiting = asked
        let answered = { (said: String, signIns: [(id: String, on: Bool)]) in
            if let json = parse(said) {
                if json["pending"] as? Bool == true {
                    self.look.recoveryReason = json["reason"] as? String ?? self.look.recoveryReason
                    if self.popover.isShown { self.draw() }
                    return
                }
                var settings = Look(json)
                settings.mindFailure = self.look.mindFailure
                settings.recoveryReason = self.look.recoveryReason
                settings.recoveryFailed = self.look.recoveryFailed
                self.look = settings
            }
            self.plans = signIns
            if let waiting, self.asked == waiting, self.look.places.first(where: { $0.id == waiting })?.need.isEmpty == true {
                self.asked = nil
                self.change(["profile": waiting])
            }
            if self.popover.isShown { self.draw() }
        }
        if dry { return answered(vx(["settings", "menu"]).said, waiting == nil ? plans : subscriptions()) }
        DispatchQueue.global().async {
            let said = vx(["settings", "menu"]).said
            let signIns = waiting == nil ? self.plans : subscriptions()
            DispatchQueue.main.async { answered(said, signIns) }
        }
    }

    /// One change from the panel, shown at once, then made through the settings package (./vx settings menu apply).
    func change(_ want: [String: Any]) {
        if let ears = want["ears"] as? Bool { look.ears = ears }
        if let mode = want["mode"] as? String { look.mode = mode }
        if let eyes = want["eyes"] as? Bool { look.eyesOn = eyes }
        if let profile = want["profile"] as? String { look.profile = profile; look.applying = "restarting" }
        told = ""
        if popover.isShown { draw() }
        let body = String(data: try! JSONSerialization.data(withJSONObject: want, options: .sortedKeys), encoding: .utf8)!
        note("panel: \(want.keys.sorted().joined(separator: ", "))")
        let answered = { (said: String) in
            if let json = parse(said) {
                if let menu = json["menu"] as? [String: Any] { self.look = Look(menu) }
                self.told = (json["ok"] as? Bool ?? false) ? "" : json["why"] as? String ?? ""
            } else {
                self.told = "That did not change. Try again in a moment."
            }
            if self.popover.isShown { self.draw() }
        }
        if dry { return answered(vx(["settings", "menu", "apply"], input: body).said) }
        DispatchQueue.global().async {
            let said = vx(["settings", "menu", "apply"], input: body).said
            DispatchQueue.main.async { answered(said) }
        }
    }

    func act(_ what: String) {
        guard !repairing else { return }
        switch what {
        case "ears":
            if !up { change(["ears": true]); return begin() }  // (resting: she starts, the page opens, its microphone on)
            let on = !look.ears
            change(["ears": on])
            if on && !look.open { go(URL(string: page)!) }  // (her agent turns its microphone on)
        case "eyes": change(["eyes": !look.eyesOn])
        case "wing", "listen": change(["mode": look.mode == what ? "talk" : what])
        case let place where place.hasPrefix("place:"):
            let id = String(place.dropFirst(6))
            guard let chosen = look.places.first(where: { $0.id == id }) else { return }
            if id == look.profile && (!id.hasPrefix("small-") || chosen.need.isEmpty) { return }
            switch chosen.need {
            case "": change(["profile": id])
            case "signin":  // (its sign-ins, here; once one is made, she switches to it by herself)
                asked = id
                if dry { return print("sign-ins: " + subscriptions().filter { chosen.plans.contains($0.id) }.map { $0.id }.joined(separator: " ")) }
                draw()
                read()
            default: go(URL(string: page + "/settings#accounts")!)
            }
        case let plan where plan.hasPrefix("signin:"):
            let id = String(plan.dropFirst(7))
            note("started the \(planNames[id] ?? id) sign-in")
            if dry { _ = vx(["subscriptions", id]); return }
            if firstWindow, let account = accounts.first(where: { $0.connect == id }) {
                accountErrors[account.id] = nil
                if id == "chatgpt_mind" && account.privacy != nil {
                    chatgptConsent = true
                    say(.accounts)
                    return
                }
                if account.installed == true { return connect(account) }
                queuedAccounts.insert(account.id)
                pendingAccounts.insert(account.id)
                say(.accounts)
                readAccounts()
            } else if id == "chatgpt_mind" {
                go(URL(string: page + "/settings#account-openai")!)
            } else {
                DispatchQueue.global().async { _ = vx(["subscriptions", id]); DispatchQueue.main.async { self.read() } }
            }
        case "chatgpt-connect":
            guard chatgptConsent, let account = accounts.first(where: { $0.connect == "chatgpt_mind" }) else { return }
            chatgptConsent = false
            connect(account)
        case "chatgpt-cancel":
            chatgptConsent = false
            say(.accounts)
        case "chatgpt-stop":
            DispatchQueue.global().async {
                _ = vx(["subscriptions", "chatgpt_mind", "--cancel"])
                DispatchQueue.main.async { self.readAccounts() }
            }
        case let key where key.hasPrefix("key:"):
            editingKey = String(key.dropFirst(4))
            say(.accounts)
            face.focusKey()
        case "key-cancel":
            editingKey = nil
            say(.accounts)
        case "page":
            if up || connected {
                go(URL(string: page)!)
            } else { begin() }
        case "telegram": if let url = bot() { go(url) }
        case "life":  // (his Life folder, in Finder)
            let open = { let folder = vx(["life"]).said.trimmingCharacters(in: .whitespacesAndNewlines)
                         if !folder.isEmpty { go(URL(fileURLWithPath: folder)) } }
            if dry { open() } else { DispatchQueue.global().async { open() } }
        case let start where start.hasPrefix("start:"): begin(place: String(start.dropFirst(6)))
        case "settings":
            if !look.recoveryReason.isEmpty { repairSettings() }
            else if up || connected || silent || pending { go(URL(string: page + "/settings")!) } else { begin() }
        case "doctor":
            if dry { return print(vx(["doctor"]).said) }
            DispatchQueue.global().async {
                let result = vx(["doctor"])
                DispatchQueue.main.async { self.say(.recoveryDoctor(said: result.said.trimmingCharacters(in: .whitespacesAndNewlines))) }
            }
        case "backup-current": repair(["backup"], title: "Saving current files")
        case let copy where copy.hasPrefix("restore:"):
            repair(["restore", String(copy.dropFirst(8)), "--yes"], title: "Restoring backup")
        case "quit": quit()
        case "privacy": go(privacy)
        case "mind":  // (her mind did not answer: Settings opens at Brain, where another is chosen; she starts on it by herself)
            go(URL(string: page + "/settings#brain")!)
            note("opened Settings at Brain: her mind did not answer")
            if dry { return }
            window?.close()
            window = nil
        case "again": offlineTries = 0; begin()
        case "tools":
            if let tool = Installer(rawValue: what) { openInstaller(tool) }
        default: break
        }
    }

    func repairSettings(message: String = "") {
        if dry { return print("Settings: Backups") }
        DispatchQueue.global().async {
            let result = vx(["settings", "recovery"])
            let json = parse(result.said)
            let data = try? JSONSerialization.data(withJSONObject: json?["backups"] as? [[String: Any]] ?? [])
            let copies = data.flatMap { try? JSONDecoder().decode([RestoreCopy].self, from: $0) } ?? []
            DispatchQueue.main.async {
                let reason = json?["reason"] as? String ?? self.look.recoveryReason
                self.say(.recoverySettings(said: [message, reason].filter { !$0.isEmpty }.joined(separator: "\n"), copies: copies))
            }
        }
    }

    func repair(_ args: [String], title: String) {
        if dry { return print(vx(args).said) }
        repairing = true
        say(.repairing(said: title))
        DispatchQueue.global().async {
            let result = vx(args)
            DispatchQueue.main.async {
                self.repairing = false
                if result.code == 0 && args.first == "restore" {
                    self.look.recoveryReason = ""
                    self.look.recoveryFailed = false
                    note("Restored a checked backup from Settings")
                    self.begin()
                } else {
                    self.repairSettings(message: result.code == 0 ? "Current incomplete files saved." : result.said.trimmingCharacters(in: .whitespacesAndNewlines))
                }
            }
        }
    }

    func openInstaller(_ tool: Installer) {
        guard installer == nil || (installer == tool && moment == .installing(tool, retry: true)) else { return }
        installer = tool
        say(.installing(tool, retry: false))
        if dry || quietForCheck { print("launch: \(tool.rawValue)"); return }

        let began = Date()
        var failed = false
        var sawDialog = false
        var app: NSRunningApplication?
        let package = URL(fileURLWithPath: "\(logs)/Homebrew.pkg")
        let native = URL(fileURLWithPath: "/System/Library/CoreServices/Installer.app")
        NSWorkspace.shared.open([package], withApplicationAt: native, configuration: .init()) { opened, error in
            DispatchQueue.main.async { app = opened; failed = error != nil }
        }
        watching?.invalidate()
        var checking = false
        watching = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { timer in
            guard !checking else { return }
            checking = true
            DispatchQueue.global().async {
                let ready = vx(["tools-ready", tool.rawValue]).code == 0
                DispatchQueue.main.async {
                    checking = false
                    guard timer.isValid else { return }
                    if ready {
                        timer.invalidate()
                        self.installer = nil
                        self.begin()
                        return
                    }
                    let running = app.map { !$0.isTerminated }
                        ?? NSRunningApplication.runningApplications(withBundleIdentifier: tool.bundleID).contains { !$0.isTerminated }
                    sawDialog = sawDialog || running
                    if failed || (!running && (sawDialog || Date().timeIntervalSince(began) >= 12)) {
                        self.installerEnded(tool)
                    }
                }
            }
        }
    }

    func installerEnded(_ tool: Installer) {
        if moment == .installing(tool, retry: false) { say(.installing(tool, retry: true)) }
    }

    func saveKey(_ name: String, _ value: String) {
        guard let account = accounts.first(where: { $0.key == name }) else { return }
        accountErrors[account.id] = nil
        DispatchQueue.global().async {
            let result = vx(["first-run-key", name], input: value)
            DispatchQueue.main.async {
                if result.code == 0 {
                    self.editingKey = nil
                    if let index = self.accounts.firstIndex(where: { $0.id == account.id }) {
                        self.accounts[index].keySaved = true
                    }
                    self.connectionChanged()
                } else {
                    let message = result.said.trimmingCharacters(in: .whitespacesAndNewlines)
                    self.accountErrors[account.id] = message.isEmpty ? "Could not save the key. Try again." : message
                }
                if self.firstWindow && self.moment == .accounts { self.say(.accounts) }
            }
        }
    }

    func readAccounts() {
        guard firstWindow, look.recoveryReason.isEmpty, !statusInFlight else { return }
        statusInFlight = true
        DispatchQueue.global().async {
            let result = vx(["setup-accounts"])
            let ready = setupAccounts(result.said.data(using: .utf8))
            DispatchQueue.main.async {
                self.statusInFlight = false
                guard let ready, self.firstWindow else { return }
                let changed = self.accounts != ready
                self.accounts = ready
                for account in ready where account.installed == true && self.queuedAccounts.remove(account.id) != nil {
                    self.connect(account)
                }
                if changed && self.moment == .accounts { self.say(.accounts) }
            }
        }
    }

    func connect(_ account: SetupAccount) {
        if account.signedIn == true { self.pendingAccounts.remove(account.id); return }
        if account.connect == "chatgpt_mind" && account.installed != true {
            queuedAccounts.insert(account.id)
            pendingAccounts.insert(account.id)
            say(.accounts)
            readAccounts()
            return
        }
        let command = ["subscriptions", account.connect]
        pendingAccounts.insert(account.id)
        say(.accounts)
        DispatchQueue.global().async {
            let result = vx(command)
            let chatgptState = account.connect == "chatgpt_mind" ? parse(result.said)?["state"] as? String : nil
            DispatchQueue.main.async {
                self.pendingAccounts.remove(account.id)
                if result.code == 0 && (chatgptState == nil || chatgptState == "connected" || chatgptState == "limited") {
                    if let index = self.accounts.firstIndex(where: { $0.id == account.id }) {
                        self.accounts[index].signedIn = true
                    }
                    if !account.background { self.connectionChanged() }
                } else {
                    let known = [
                        "expired": "Sign-in expired.", "denied": "Sign-in was refused.", "cancelled": "Sign-in cancelled.",
                        "keychain_locked": "Unlock your Keychain.", "busy": "Sign-in is already open.",
                        "scope_missing": "Plan access missing.",
                    ]
                    let outcome = chatgptState ?? result.said.trimmingCharacters(in: .whitespacesAndNewlines)
                    self.accountErrors[account.id] = known[outcome] ?? "Could not connect."
                }
                if self.firstWindow && self.moment == .accounts { self.say(.accounts) }
            }
        }
    }

    func connectionChanged() {
        accountErrors["setup"] = nil
        if firstWindow && !up && starter == nil { begin() }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        openAsked()
        return false
    }

    func trackFirstWindow() {
        let pending = ".first-conversation-pending"
        firstWindow = !here(".first-ready") && (!here(".setup-done") || here(".first-run") || here(pending))
        if firstWindow, let facts = try? JSONSerialization.data(withJSONObject: firstContext) {
            let fm = FileManager.default
            try? fm.createDirectory(atPath: logs, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            let path = "\(logs)/\(pending)"
            if !here(pending) || (try? Data(contentsOf: URL(fileURLWithPath: path)).isEmpty) == true {
                fm.createFile(atPath: path, contents: facts, attributes: [.posixPermissions: 0o600])
            }
        }
    }

    var firstContext: [String: Any] {
        ["first_conversation": true, "mac_name": NSFullUserName(), "locale": Locale.current.identifier]
    }

    func opening() {
        trackFirstWindow()
        if firstWindow { say(.opening) }
        DispatchQueue.global().async {
            let (said, _, allowed) = vx(["status"])
            let resource = Bundle.main.url(forResource: "SetupAccounts", withExtension: "json")
            let data = resource.flatMap { try? Data(contentsOf: $0) } ?? vx(["setup-catalog"]).said.data(using: .utf8)
            DispatchQueue.main.async {
                self.blocked = !allowed
                self.accounts = setupAccounts(data) ?? []
                self.show(said)
                self.openAsked()
            }
        }
    }

    func openAsked() {
        if !firstWindow && here(".first-conversation-pending") && !here(".first-ready") {
            trackFirstWindow()
        }
        if blocked {
            say(.privacy)
        } else if look.recoveryFailed {
            say(.recovery(said: look.recoveryReason))
        } else if up || (connected && !firstWindow) {
            openConversation()
        } else {
            if firstWindow && window?.isVisible != true {
                say(.accounts)
                window?.makeKeyAndOrderFront(nil)
            }
            begin()
        }
    }

    func openConversation() {
        if firstWindow {
            guard didAnswer else { return }
            let connected = accounts.flatMap { account in
                [(account.signedIn == true, "\(account.product) subscription"),
                 (account.keySaved == true, "\(account.product) API key")].compactMap { $0.0 ? $0.1 : nil }
            }
            var context = firstContext
            context["connected"] = connected
            if !here(".first-ready"), let data = try? JSONSerialization.data(withJSONObject: context) {
                FileManager.default.createFile(atPath: "\(logs)/.first-ready", contents: data, attributes: [.posixPermissions: 0o600])
            }
            if here(".first-ready") { try? FileManager.default.removeItem(atPath: "\(logs)/.first-conversation-pending") }
            firstWindow = false
        }
        window?.orderOut(nil)
        go(URL(string: page)!)
    }

    func begin(place: String? = nil) {
        if dry { return print("start" + (place.map { " \($0)" } ?? "")) }
        if starter != nil || installer != nil {
            window?.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        watching?.invalidate()
        accountErrors["setup"] = nil
        starting = Date()
        let liveSetup = firstWindow && window?.isVisible == true
        if moment != .downloadPaused { say(firstWindow ? .accounts : .starting) }
        face.advance(max(0.08, progress))
        readAccounts()
        var last = ""
        // Only this window's start gets a pipe. EOF withdraws setup attendance.
        setupInput = liveSetup ? Pipe() : nil
        starter = startHer(place: place, setupInput: setupInput, line: { said in
            last = said
            self.heard(said)
        }, done: { code in
            self.closeSetupInput()
            DispatchQueue.global().async {
                let said = vx(["status"]).said
                let why = (try? String(contentsOfFile: "\(logs)/blocked", encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                DispatchQueue.main.async {
                    self.starting = nil
                    self.show(said)
                    self.starter = nil
                    if self.firstWindow && self.window?.isVisible != true { return }
                    if code == 0 && (self.up || (self.connected && !self.firstWindow)) {
                        self.offlineTries = 0
                        self.openConversation()
                    } else {
                        self.stopped(why, last: plain(last))
                    }
                }
            }
        })
    }

    func heard(_ said: String) {
        let stages: [(String, CGFloat)] = [
            ("download: the system tools", 0.12), ("download: the Workers", 0.23),
            ("download: the model server", 0.27), ("download: Viventium's parts", 0.31),
            ("download: the voice", 0.40), ("download: the page", 0.51), ("download: hearing", 0.55),
            ("download: the brain", 0.59), ("workers: ready", 0.74), ("ui: started", 0.87), ("Ready:", 1),
        ]
        if let stage = stages.first(where: { said.hasPrefix($0.0) }), stage.1 > progress {
            progress = stage.1
            face.advance(progress)
        }
        // The retry has reached the next setup step. Until then the paused line stays steady.
        if moment == .downloadPaused && (said == "stage: starting" || said.hasPrefix("stt: started")) {
            say(firstWindow ? .accounts : .starting)
        }
    }

    func stopped(_ why: String, last: String) {
        let parts = why.isEmpty && freeGB() < 2 ? ["disk", String(freeGB() + 5)] : why.split(separator: " ").map(String.init)
        if parts.first != "offline" { offlineTries = 0 }
        switch parts.first ?? "" {
        case "disk":
            let need = Int(parts.dropFirst().first ?? "") ?? 0
            say(.disk(need: need))
            watching = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { timer in
                if freeGB() >= need { timer.invalidate(); self.begin() } else { self.say(.disk(need: need)) }
            }
        case "chip": say(.chip)
        case "small-signin", "signin", "small-key", "key":
            firstWindow = true
            say(.accounts)
            readAccounts()
        case "tools":
            if let tool = Installer(rawValue: parts[0]) { openInstaller(tool) }
        case "offline":
            offlineTries += 1
            if offlineTries > 6 {
                offlineTries = 0
                say(.failed(said: "This Mac is not online."))
            } else {
                say(.offline(left: 7 - offlineTries))
                watching = Timer.scheduledTimer(withTimeInterval: 30, repeats: false) { _ in self.begin() }
            }
        case "download":
            say(.downloadPaused)
            watching?.invalidate()
            watching = Timer.scheduledTimer(withTimeInterval: 30, repeats: false) { _ in self.begin() }
        case "held": say(.failed(said: last))
        case "failed": say(.failed(said: parts.dropFirst().joined(separator: " ")))
        case "restore":
            say(.recovery(said: parts.dropFirst(2).joined(separator: " ")))
        case "mind":
            if firstWindow {
                accountErrors["setup"] = last.isEmpty ? "Viventium could not answer." : last
                say(.accounts)
            } else {
                say(.mind(said: last, again: parts.dropFirst().first == "silent"))
            }
        default:
            // Only typed progress is safe to show here: arbitrary process output can be a traceback.
            let stage = (try? String(contentsOfFile: "\(logs)/up.progress", encoding: .utf8))?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            let parts = stage.split(separator: ":", maxSplits: 1).map(String.init)
            let detail = parts.count == 2 && parts[0] == "download"
                ? "Setting up \(parts[1].trimmingCharacters(in: .whitespaces)) did not finish. Try again." : ""
            say(.failed(said: detail))
        }
    }

    func say(_ moment: Moment) {
        if quietForCheck { self.moment = moment; return }
        let changed = moment != self.moment
        if changed { note("window: \(words(moment).title)") }
        self.moment = moment
        face.show(moment, accounts: accounts, local: canRunLocal, pending: pendingAccounts,
                  errors: accountErrors, key: editingKey, chatgptConsent: chatgptConsent,
                  waiting: starting != nil || moment == .opening)
        face.submitKey = { [weak self] name, value in self?.saveKey(name, value) }
        let size = face.fittingSize
        let new = window == nil
        if window == nil {
            let made = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                                styleMask: [.titled, .closable, .fullSizeContentView], backing: .buffered, defer: false)
            made.title = "Viventium AI"
            made.appearance = NSAppearance(named: .darkAqua)
            made.titlebarAppearsTransparent = true
            made.titleVisibility = .hidden
            made.isMovableByWindowBackground = true
            made.isReleasedWhenClosed = false
            made.delegate = self
            made.isOpaque = false
            made.backgroundColor = .clear
            made.contentView = glass(around: face)
            made.center()
            window = made
        }
        if let window, !new {
            var frame = window.frameRect(forContentRect: NSRect(origin: .zero, size: size))
            frame.origin = NSPoint(x: window.frame.midX - frame.width / 2, y: window.frame.midY - frame.height / 2)
            if frame.size != window.frame.size { window.setFrame(frame, display: true, animate: window.isVisible) }
            if changed && window.isVisible && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
                window.alphaValue = 0.72
                NSAnimationContext.runAnimationGroup { animation in
                    animation.duration = 0.18
                    window.animator().alphaValue = 1
                }
            }
        }
        if new || changed {
            window?.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    func windowWillClose(_ notification: Notification) {
        closeSetupInput()
        watching?.invalidate()
    }

    func closeSetupInput() {
        try? setupInput?.fileHandleForWriting.close()
        setupInput = nil
    }

    func quit() {  // she rests, and so does this mark, until the app is opened again, ./vx up or login
        note("Quit Viventium: she rests until the app is opened again")
        popover.performClose(nil)
        NSApp.terminate(nil)
    }

    /// Quit's work: a start this app made stopped whole (a setup's downloads and builds too), then what of
    /// her had started already (./vx down: nothing, when nothing had).
    func rest() {
        if !stopping(starter) { note("a start would not stop") }
        starter = nil
        _ = vx(["down"])
    }

    // The same app owns setup and the running menu bar, including when the Dock or Command-Q quits it.
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        DispatchQueue.global().async {
            self.rest()
            DispatchQueue.main.async { NSApp.reply(toApplicationShouldTerminate: true) }
        }
        return .terminateLater
    }
}

// -- Checks that need no screen --

func flag(_ name: String) -> Int? { CommandLine.arguments.firstIndex(of: name) }

/// A view written to a PNG, at twice its size, in dark or light, on a plain tone (the glass and the panel's arrow are
/// drawn by macOS on screen and are not in a picture).
func picture(_ view: NSView, to file: String, dark: Bool) {
    let appearance = NSAppearance(named: dark ? .darkAqua : .aqua)!
    view.appearance = appearance
    view.layoutSubtreeIfNeeded()
    let size = view.fittingSize
    view.frame = NSRect(origin: .zero, size: size)
    view.layoutSubtreeIfNeeded()
    guard let drawn = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return }
    view.cacheDisplay(in: view.bounds, to: drawn)
    let out = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width * 2), pixelsHigh: Int(size.height * 2), bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    out.size = size
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: out)
    appearance.performAsCurrentDrawingAppearance {
        graphite.setFill()
        NSBezierPath(roundedRect: NSRect(origin: .zero, size: size), xRadius: 22, yRadius: 22).fill()
    }
    drawn.draw(in: NSRect(origin: .zero, size: size), from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: nil)
    NSGraphicsContext.restoreGraphicsState()
    try? out.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: file))
}

/// The panel as it would open this second (./vx status and ./vx settings menu, read now); `starting`: as it is while
/// this app is starting her (a moment only the running app knows).
func panelNow(starting: Bool = false) -> (Now, Look) {
    let (status, _, allowed) = vx(["status"])
    var look = parse(vx(["settings", "menu"]).said).map(Look.init) ?? Look()
    look.mindFailure = mindFailure(status)
    look.recoveryReason = restoreReason(status)
    look.recoveryFailed = status.contains("restore blocked: yes")
    let now: Now = !allowed ? .blocked : !look.recoveryReason.isEmpty ? .recovery : isUp(status) ? .ready : starting || asking(status) ? .starting :
        awaitingAnswer(status) ? .connected : mute(status) ? .silent : .resting
    return (now, look)
}

// `viventium-menubar ROOT --mark FILE.png`: her mark as the menu bar draws it, written large, to look at (a check).
if let at = flag("--mark"), CommandLine.arguments.count > at + 1 {
    let side = 180
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: side, pixelsHigh: side, bitsPerSample: 8, samplesPerPixel: 4,
                                  hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    NSColor.white.setFill()
    NSRect(x: 0, y: 0, width: side, height: side).fill()
    mark(dim: false).draw(in: NSRect(x: 0, y: 0, width: side, height: side))
    try? bitmap.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: CommandLine.arguments[at + 1]))
    exit(0)
}

// `viventium-menubar ROOT --menu`: the panel exactly as it would open right now, one line per control (a check that
// needs no screen): its name, then "on" (lit) or "dim" with what it needs and what a click does; a line it writes is
// quoted; nothing it does not show is printed.
if flag("--menu") != nil {
    _ = NSApplication.shared
    let (now, look) = panelNow()
    let line = stateLine(now, look)
    if !line.isEmpty { print("\"\(line)\"") }
    if now == .blocked {
        print("Allow it in System Settings")
    } else {
        let (her, places, small) = controls(now, look, bot: FileManager.default.fileExists(atPath: "\(logs)/telegram-bot.json"))
        for c in her + (look.read ? places : []) + small {
            print([c.name.components(separatedBy: " · ").first!, c.on ? "on" : "", c.dim ? "dim: \(c.say)" : ""].filter { !$0.isEmpty }.joined(separator: " "))
        }
    }
    exit(0)
}

// `viventium-menubar ROOT --render WHAT FILE.png [light]`: one surface drawn to a picture, without a click or a screen:
// "panel" (as it would open now; "panel:starting" while it starts her), "intro" (the first time, with its title),
// "asked:PLACE" (a dimmed place clicked: its sign-ins),
// or a moment of the window: "setup", "setup:DETAIL", "starting", "ready", "disk:GB", "small-signin:GB", "chip", "signin",
// "failed:WORDS", "privacy", "terminal", "mind:WORDS" (another mind), "mind-again:WORDS" (Try again). The window's sign-ins
// are the stand-in's (./vx subscriptions).
if let at = flag("--render"), CommandLine.arguments.count > at + 2 {
    _ = NSApplication.shared
    let what = CommandLine.arguments[at + 1], file = CommandLine.arguments[at + 2]
    let dark = !CommandLine.arguments.contains("light")
    let parts = what.split(separator: ":", maxSplits: 1).map(String.init)
    let rest = parts.count > 1 ? parts[1] : ""
    switch parts[0] {
    case "panel", "asked", "tour", "hover":
        let (now, look) = panelNow(starting: rest == "starting")
        let view = Panel(frame: .zero)
        let asked = parts[0] == "asked" ? look.places.first { $0.id == rest } : nil
        view.show(now, look, signIns: asked.map { place in subscriptions().filter { place.plans.contains($0.id) } } ?? [],
                  bot: FileManager.default.fileExists(atPath: "\(logs)/telegram-bot.json"),
                  highlight: parts[0] == "tour" ? rest : nil)
        if parts[0] == "hover" {
            func hover(_ parent: NSView) {
                for child in parent.subviews {
                    if let disc = child as? Disc, disc.accessibilityLabel() == rest { disc.hovering = true }
                    hover(child)
                }
            }
            hover(view)
        }
        picture(view, to: file, dark: dark)
    default:
        let moments: [String: Moment] = [
            "opening": .opening, "setup": .accounts, "starting": .starting,
            "disk": .disk(need: Int(rest) ?? 0), "chip": .chip, "small-signin": .accounts, "signin": .accounts,
            "failed": .failed(said: rest), "privacy": .privacy, "tools": .installing(.tools, retry: rest == "retry"),
            "restore": .recovery(said: rest),
            "restore-settings": .recoverySettings(said: rest, copies: [RestoreCopy(name: "synthetic", made: "2026-01-01 12:00:00")]),
            "restore-doctor": .recoveryDoctor(said: rest),
            "offline": .offline(left: 6), "download": .downloadPaused,
            "mind": .mind(said: "This Mac could not run its model.", again: false),
            "mind-again": .mind(said: "This Mac’s model is not answering.", again: true)]
        guard let moment = moments[parts[0]] else { print("unknown: \(what)"); exit(2) }
        let view = Face(frame: .zero)
        var accounts = setupAccounts(vx(["setup-catalog"]).said.data(using: .utf8)) ?? []
        if rest == "connected", let idx = accounts.indices.last { accounts[idx].signedIn = true }
        if rest == "connecting", let idx = accounts.indices.last { accounts[idx].installed = true }
        view.show(moment, accounts: accounts, local: parts[0] != "small-signin" && rest != "small",
                  pending: rest == "connecting" ? ["xai"] : [], errors: rest == "failure" ? ["xai": "Sign-in expired."] : [:],
                  key: rest == "key" ? accounts.last?.key : nil, chatgptConsent: rest == "chatgpt-consent",
                  waiting: [.opening, .starting, .accounts].contains(moment))
        view.advance(rest == "connecting" ? 0.55 : 0.22)
        picture(view, to: file, dark: true)
    }
    exit(0)
}

// `viventium-menubar ROOT --act WHAT`: one click on the panel as it would open now, done without a screen (a check): the
// change it makes goes through ./vx as a click's does, and what it would open is printed ("open URL", "start").
if let at = flag("--act"), CommandLine.arguments.count > at + 1 {
    _ = NSApplication.shared
    let (now, look) = panelNow()
    let clicked = Bar()
    clicked.look = look
    clicked.up = now == .ready
    clicked.connected = now == .connected
    clicked.silent = now == .silent
    clicked.pending = now == .starting  // (as it opens now: only a start at work not yet heard her mind)
    clicked.blocked = now == .blocked
    switch CommandLine.arguments[at + 1] {
    case "first-open":
        clicked.trackFirstWindow()
        if clicked.up { clicked.openConversation() }
    case "look": clicked.read()  // (what the panel does when it reads again: a place asked for, switched to once it can run)
    case "tick":  // (the five-second look with the panel open: what it then writes)
        clicked.shownForCheck = true
        clicked.tick()
        print("\"\(stateLine(now, clicked.look))\"")
    default: clicked.act(CommandLine.arguments[at + 1])
    }
    exit(0)
}

// `viventium-menubar ROOT --stop-dry WHY [WORDS]`: the window a start that stopped for WHY (as logs/blocked says it) shows:
// its title, its line, and its one way forward, one per line (a check that needs no screen).
if let at = flag("--stop-dry"), CommandLine.arguments.count > at + 1 {
    _ = NSApplication.shared
    let stopped = Bar()
    stopped.quietForCheck = true
    for _ in 0..<(Int(ProcessInfo.processInfo.environment["VX_TRIES"] ?? "1") ?? 1) {
        stopped.stopped(CommandLine.arguments[at + 1], last: CommandLine.arguments.count > at + 2 ? CommandLine.arguments[at + 2] : "")
    }
    if let next = ProcessInfo.processInfo.environment["VX_NEXT_STOP"] { stopped.stopped(next, last: "") }
    if let tool = stopped.installer,
       ["closed", "failed"].contains(ProcessInfo.processInfo.environment["VX_INSTALLER_RESULT"] ?? "") {
        stopped.installerEnded(tool)
    }
    let (title, detail) = words(stopped.moment)
    print(title)
    print(detail ?? "")
    switch stopped.moment {
    case .failed: print("button: Try again")
    case .mind(_, let again): print(again ? "button: Try again" : "button: Choose another mind")
    case .recovery: print("button: Choose backup\nbutton: Try again\nbutton: Doctor")
    case .offline, .downloadPaused: print(stopped.watching?.isValid == true ? "tries again by itself" : "")
    case .disk: print(stopped.watching?.isValid == true ? "goes on by itself" : "")
    case .accounts: print("account rows")
    case .installing(_, true): print("button: Try again")
    case .installing(_, false): break
    default: print("")
    }
    exit(0)
}

// `viventium-menubar ROOT --lines-dry LINE...`: the window's one line under its title after each line of `./vx up`, as
// the app hears them while it starts her, one per line ("" when it has none; a check that needs no screen).
if let at = flag("--lines-dry") {
    _ = NSApplication.shared
    let starting = Bar()
    starting.quietForCheck = true
    starting.moment = .starting
    for said in CommandLine.arguments.dropFirst(at + 1) {
        starting.heard(said.trimmingCharacters(in: .whitespaces))
        print(words(starting.moment).detail ?? "")
    }
    exit(0)
}

// `viventium-menubar ROOT --quit-dry`: a start made as the app makes it, then Quit's work: whether all of it stopped.
if flag("--quit-dry") != nil {
    _ = NSApplication.shared
    let quitting = Bar()
    quitting.starter = startHer(line: { _ in }, done: { _ in })
    for _ in 0..<50 where !here("up-child") { usleep(100_000) }
    quitting.rest()
    print(quitting.starter == nil ? "stopped" : "running")
    exit(0)
}

// `viventium-menubar ROOT --icon FILE.png SIDE`: the app's icon at that size (vx makes the app's icon set with it).
if let at = flag("--icon"), CommandLine.arguments.count > at + 2, let side = Int(CommandLine.arguments[at + 2]), side > 0 {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: side, pixelsHigh: side, bitsPerSample: 8, samplesPerPixel: 4,
                                  hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    icon(side: CGFloat(side)).draw(in: NSRect(x: 0, y: 0, width: side, height: side))
    try? bitmap.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: CommandLine.arguments[at + 1]))
    exit(0)
}

// `viventium-menubar [ROOT] --open-dry`: what opening the app would do now (a check that needs no screen): "start" while
// she rests, "page" while she runs, "privacy" while macOS keeps the folder closed.
if flag("--open-dry") != nil {
    let (said, _, allowed) = vx(["status"])
    print(!allowed ? "privacy" : said.contains("restore blocked: yes") ? "recovery" : isUp(said) || awaitingAnswer(said) ? "page" : "start")
    exit(0)
}

let app = NSApplication.shared
let bar = Bar()
if opened {
    if packaged {
        do { try installPackagedRuntime() } catch {
            app.setActivationPolicy(.regular)
            app.activate(ignoringOtherApps: true)
            let alert = NSAlert()
            alert.messageText = "Viventium could not set up its folder"
            alert.informativeText = (error as? CocoaError)?.code == .fileWriteFileExists
                ? "This home folder already has a different Viventium AI installation. Open its matching app."
                : "Check the free space on this Mac and open Viventium AI again."
            alert.runModal()
            exit(1)
        }
    }
    // One app, one mark: when hers runs already, it is asked to open her, and this one goes.
    let mine = ProcessInfo.processInfo.processIdentifier
    let others = NSRunningApplication.runningApplications(withBundleIdentifier: Bundle.main.bundleIdentifier ?? "ai.viventium.light")
        .filter { $0.processIdentifier != mine && (!packaged || $0.bundleURL == Bundle.main.bundleURL) }
    if !others.isEmpty {
        DistributedNotificationCenter.default().postNotificationName(openNote, object: openNoteObject, userInfo: nil, deliverImmediately: true)
        exit(0)
    }
    app.delegate = bar
    app.setActivationPolicy(.regular)  // (opened by a person: its window and its Dock icon while it opens her)
} else {
    app.delegate = bar
    app.setActivationPolicy(.accessory)  // no Dock icon, no window
}
app.run()
