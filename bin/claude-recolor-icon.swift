// claude-recolor-icon.swift <input.png> <output.png> <hueDegrees>
//
// Hue-rotates Claude's icon to a target hue and deepens the tile slightly.
// A direct port of the original Python/PIL implementation, rewritten against
// CoreGraphics so it depends only on what ships with macOS -- python3 + PIL +
// numpy kept disappearing under Homebrew and OS upgrades, which silently broke
// icon generation.
//
// Works in HSV so the starburst, grain, inner shading and drop shadow survive:
// only hue moves. The tile is then deepened (weighted by saturation) so the
// near-white starburst keeps its contrast at small sizes.

import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write(("error: " + msg + "\n").data(using: .utf8)!)
    exit(1)
}

let args = CommandLine.arguments
guard args.count == 4, let hueDeg = Double(args[3]),
      hueDeg.isFinite, hueDeg >= 0, hueDeg <= 359 else {
    fail("usage: claude-recolor-icon.swift <input.png> <output.png> <hueDegrees>")
}
let inURL = URL(fileURLWithPath: args[1])
let outURL = URL(fileURLWithPath: args[2])
let targetHue = hueDeg / 360.0

guard let src = CGImageSourceCreateWithURL(inURL as CFURL, nil),
      let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else {
    fail("could not read \(inURL.path)")
}

let w = img.width, h = img.height
let cs = CGColorSpaceCreateDeviceRGB()
// Contexts cannot hold non-premultiplied alpha, so we unpremultiply by hand.
guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8,
                          bytesPerRow: w * 4, space: cs,
                          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
    fail("could not create bitmap context")
}
ctx.draw(img, in: CGRect(x: 0, y: 0, width: w, height: h))
guard let buf = ctx.data else { fail("no bitmap data") }
let px = buf.bindMemory(to: UInt8.self, capacity: w * h * 4)

@inline(__always) func rgb2hsv(_ r: Double, _ g: Double, _ b: Double) -> (Double, Double, Double) {
    let mx = max(r, g, b), mn = min(r, g, b), d = mx - mn
    var hh = 0.0
    if d > 1e-9 {
        if mx == r { hh = ((g - b) / d).truncatingRemainder(dividingBy: 6) }
        else if mx == g { hh = (b - r) / d + 2 }
        else { hh = (r - g) / d + 4 }
        hh /= 6
        if hh < 0 { hh += 1 }
    }
    return (hh, mx > 1e-9 ? d / mx : 0, mx)
}

@inline(__always) func hsv2rgb(_ hh: Double, _ s: Double, _ v: Double) -> (Double, Double, Double) {
    let h6 = hh * 6, i = Int(floor(h6)) % 6, f = h6 - floor(h6)
    let p = v * (1 - s), q = v * (1 - s * f), t = v * (1 - s * (1 - f))
    switch (i + 6) % 6 {
    case 0: return (v, t, p)
    case 1: return (q, v, p)
    case 2: return (p, v, t)
    case 3: return (p, q, v)
    case 4: return (t, p, v)
    default: return (v, p, q)
    }
}

// Pass 1: the tile's own hue = median hue of the saturated pixels.
var hues: [Double] = []
hues.reserveCapacity(w * h / 4)
for i in stride(from: 0, to: w * h * 4, by: 4) {
    let a = Double(px[i + 3]) / 255.0
    guard a > 0.004 else { continue }
    let r = Double(px[i]) / 255.0 / a
    let g = Double(px[i + 1]) / 255.0 / a
    let b = Double(px[i + 2]) / 255.0 / a
    let (hh, s, _) = rgb2hsv(min(r, 1), min(g, 1), min(b, 1))
    if s > 0.25 { hues.append(hh) }
}
guard !hues.isEmpty else { fail("no saturated pixels found in source icon") }
hues.sort()
let sourceHue = hues[hues.count / 2]
let delta = targetHue - sourceHue

// Pass 2: rotate hue, then deepen the tile only (weighted by saturation).
for i in stride(from: 0, to: w * h * 4, by: 4) {
    let a = Double(px[i + 3]) / 255.0
    guard a > 0.004 else { continue }
    let r0 = min(Double(px[i]) / 255.0 / a, 1)
    let g0 = min(Double(px[i + 1]) / 255.0 / a, 1)
    let b0 = min(Double(px[i + 2]) / 255.0 / a, 1)

    var (hh, s, v) = rgb2hsv(r0, g0, b0)
    hh = (hh + delta).truncatingRemainder(dividingBy: 1)
    if hh < 0 { hh += 1 }
    var (r, g, b) = hsv2rgb(hh, s, v)

    let wgt = min(max((s - 0.12) / 0.25, 0), 1)
    r *= (1 - 0.16 * wgt); g *= (1 - 0.16 * wgt); b *= (1 - 0.16 * wgt)
    let grey = (r + g + b) / 3
    r = grey + (r - grey) * (1 + 0.35 * wgt)
    g = grey + (g - grey) * (1 + 0.35 * wgt)
    b = grey + (b - grey) * (1 + 0.35 * wgt)

    px[i]     = UInt8(min(max(r, 0), 1) * a * 255 + 0.5)
    px[i + 1] = UInt8(min(max(g, 0), 1) * a * 255 + 0.5)
    px[i + 2] = UInt8(min(max(b, 0), 1) * a * 255 + 0.5)
    _ = v; _ = s
}

guard let outImg = ctx.makeImage(),
      let dest = CGImageDestinationCreateWithURL(outURL as CFURL, UTType.png.identifier as CFString, 1, nil) else {
    fail("could not create output image")
}
CGImageDestinationAddImage(dest, outImg, nil)
guard CGImageDestinationFinalize(dest) else { fail("could not write \(outURL.path)") }

let fmt = String(format: "  tile hue %.1f deg -> %.1f deg  (%dx%d)",
                 sourceHue * 360, targetHue * 360, w, h)
print(fmt)
