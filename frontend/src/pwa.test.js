import { readFileSync } from "node:fs";
import { describe, it, expect } from "vitest";

const read = (path, encoding = "utf-8") =>
  readFileSync(new URL(path, import.meta.url), encoding);

describe("PWA manifest", () => {
  const manifest = JSON.parse(read("../public/manifest.json"));

  it("is installable: name, start_url, standalone display", () => {
    expect(manifest.name).toBe("Docker Auto-Heal Service");
    expect(manifest.start_url).toBe("/");
    expect(manifest.display).toBe("standalone");
  });

  it("references 192px, 512px and maskable icons that exist", () => {
    const sizes = manifest.icons.map((i) => i.sizes);
    expect(sizes).toContain("192x192");
    expect(sizes).toContain("512x512");
    expect(manifest.icons.some((i) => i.purpose === "maskable")).toBe(true);
    for (const asset of [...manifest.icons, ...manifest.screenshots]) {
      expect(() => read(`../public${asset.src}`)).not.toThrow();
    }
  });

  it("has a stable app id", () => {
    expect(manifest.id).toBe("/");
  });

  it("declares the real pixel size of every icon and screenshot", () => {
    // PNG header: width and height are big-endian uint32 at bytes 16 and 20.
    const size = (src) => {
      const png = read(`../public${src}`, null);
      return `${png.readUInt32BE(16)}x${png.readUInt32BE(20)}`;
    };
    for (const asset of [...manifest.icons, ...manifest.screenshots]) {
      expect(asset.sizes, asset.src).toBe(size(asset.src));
    }
  });

  it("is linked from index.html", () => {
    expect(read("../index.html")).toContain(
      'rel="manifest" href="/manifest.json"',
    );
  });
});
