// Theseus's icons. Ivory on Aegean blue: the sea he sailed from Athens to Crete and back.
// Run from the repo root: swift scripts/make-icon.swift, then pnpm --filter theseus-desktop icons
import AppKit
let ivory = NSColor(red: 0.953, green: 0.918, blue: 0.839, alpha: 1)
let aegean = (NSColor(red: 0.075, green: 0.216, blue: 0.341, alpha: 1), NSColor(red: 0.043, green: 0.141, blue: 0.239, alpha: 1))
func canvas(_ px: Int, _ draw: () -> Void) -> NSBitmapImageRep {
  let r = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
  NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: r)
  let t = NSAffineTransform(); t.scale(by: CGFloat(px) / 1024); t.concat()
  NSColor.clear.set(); NSRect(x: 0, y: 0, width: 1024, height: 1024).fill(using: .copy)
  draw(); NSGraphicsContext.current = nil; return r
}
func tile(_ c: (NSColor, NSColor)) {
  let p = NSBezierPath(roundedRect: NSRect(x: 100, y: 100, width: 824, height: 824), xRadius: 185, yRadius: 185)
  NSGradient(starting: c.0, ending: c.1)!.draw(in: p, angle: -90)
}
// Theseus: an Athenian ship under one square sail, the way it appears on Greek vases. Three shapes.
func ship(_ color: NSColor, scale s: CGFloat = 1, bold: CGFloat = 0) {
  NSGraphicsContext.saveGraphicsState()
  let t = NSAffineTransform(); t.translateX(by: 512, yBy: 512); t.scale(by: s); t.translateX(by: -512, yBy: -512); t.concat()
  color.set()
  // sail: a square sail with a gentle belly along the foot
  let sail = NSBezierPath()
  sail.move(to: NSPoint(x: 344, y: 716))
  sail.line(to: NSPoint(x: 680, y: 716))
  sail.curve(to: NSPoint(x: 680, y: 470), controlPoint1: NSPoint(x: 700, y: 640), controlPoint2: NSPoint(x: 700, y: 545))
  sail.curve(to: NSPoint(x: 344, y: 470), controlPoint1: NSPoint(x: 600, y: 430), controlPoint2: NSPoint(x: 424, y: 430))
  sail.curve(to: NSPoint(x: 344, y: 716), controlPoint1: NSPoint(x: 324, y: 545), controlPoint2: NSPoint(x: 324, y: 640))
  sail.close(); sail.fill()
  // yard and mast
  NSBezierPath(roundedRect: NSRect(x: 306 - bold, y: 728, width: 412 + 2 * bold, height: 20 + bold), xRadius: 10, yRadius: 10).fill()
  NSBezierPath(rect: NSRect(x: 503 - bold / 2, y: 370, width: 18 + bold, height: 410)).fill()
  // hull: ram low at the bow (left), sweeping up to a curled stern (right)
  let hull = NSBezierPath()
  hull.move(to: NSPoint(x: 196, y: 338))           // tip of the ram
  hull.curve(to: NSPoint(x: 268, y: 392), controlPoint1: NSPoint(x: 226, y: 350), controlPoint2: NSPoint(x: 250, y: 372))
  hull.curve(to: NSPoint(x: 690, y: 392), controlPoint1: NSPoint(x: 400, y: 362), controlPoint2: NSPoint(x: 570, y: 362))
  hull.curve(to: NSPoint(x: 800, y: 560), controlPoint1: NSPoint(x: 756, y: 410), controlPoint2: NSPoint(x: 800, y: 470))
  hull.curve(to: NSPoint(x: 762, y: 610), controlPoint1: NSPoint(x: 802, y: 585), controlPoint2: NSPoint(x: 786, y: 606))
  hull.curve(to: NSPoint(x: 830, y: 540), controlPoint1: NSPoint(x: 800, y: 616), controlPoint2: NSPoint(x: 830, y: 585))
  hull.curve(to: NSPoint(x: 684, y: 300), controlPoint1: NSPoint(x: 830, y: 430), controlPoint2: NSPoint(x: 780, y: 330))
  hull.curve(to: NSPoint(x: 290, y: 300), controlPoint1: NSPoint(x: 560, y: 276), controlPoint2: NSPoint(x: 410, y: 276))
  hull.curve(to: NSPoint(x: 196, y: 338), controlPoint1: NSPoint(x: 250, y: 308), controlPoint2: NSPoint(x: 222, y: 322))
  hull.close(); hull.fill()
  NSGraphicsContext.restoreGraphicsState()
}
func save(_ r: NSBitmapImageRep, _ p: String) { try! r.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: p)) }
save(canvas(1024) { tile(aegean); ship(ivory) }, "apps/desktop/app-icon.png")
save(canvas(44) { ship(.black, scale: 1.34, bold: 14) }, "apps/desktop/src-tauri/icons/tray.png")
