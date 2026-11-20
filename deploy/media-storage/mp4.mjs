// Inspect top-level ISO BMFF boxes while hashing a stream; never buffer the movie.
export class Mp4Inspector {
  constructor(size) { this.size = size; this.position = 0; this.header = Buffer.alloc(0); this.remaining = 0; this.found = new Set(); this.boxes = 0; }
  write(data) {
    let cursor = 0;
    while (cursor < data.length) {
      if (this.remaining > 0) {
        const length = Math.min(this.remaining, data.length - cursor);
        if (this.kind === 'ftyp') this.brands = Buffer.concat([this.brands, data.subarray(cursor, cursor + length)]);
        cursor += length; this.position += length; this.remaining -= length;
        if (!this.remaining) this.finishBox();
        continue;
      }
      const target = this.header.length >= 8 && this.header.readUInt32BE(0) === 1 ? 16 : 8;
      const length = Math.min(target - this.header.length, data.length - cursor);
      this.header = Buffer.concat([this.header, data.subarray(cursor, cursor + length)]);
      cursor += length; this.position += length;
      if (this.header.length < target) continue;
      let size = this.header.readUInt32BE(0);
      if (size === 1 && this.header.length < 16) continue;
      if (size === 1) size = Number(this.header.readBigUInt64BE(8));
      const start = this.position - this.header.length;
      if (size === 0) size = this.size - start;
      if (!Number.isSafeInteger(size) || size < this.header.length || size > this.size - start || ++this.boxes > 10000) throw new Error('INVALID_MP4');
      this.kind = this.header.toString('ascii', 4, 8);
      this.remaining = size - this.header.length;
      if (['moov', 'mdat'].includes(this.kind) && !this.remaining) throw new Error('INVALID_MP4');
      if (this.kind === 'ftyp' && (this.remaining < 8 || this.remaining > 4096 || this.remaining % 4)) throw new Error('INVALID_MP4');
      this.brands = Buffer.alloc(0); this.header = Buffer.alloc(0);
      if (!this.remaining) this.finishBox();
    }
    if (this.position > this.size) throw new Error('INVALID_MP4');
  }
  finishBox() {
    if (this.kind === 'ftyp') {
      const supported = new Set(['isom', 'iso2', 'iso3', 'iso4', 'iso5', 'iso6', 'mp41', 'mp42', 'avc1', 'dash', 'M4V ']);
      let valid = false;
      for (let i = 0; i < this.brands.length; i += 4) if (i !== 4 && supported.has(this.brands.toString('ascii', i, i + 4))) valid = true;
      if (!valid) throw new Error('INVALID_MP4');
    }
    this.found.add(this.kind);
  }
  finish() {
    if (this.position !== this.size || this.header.length || this.remaining || !['ftyp', 'moov', 'mdat'].every(k => this.found.has(k))) throw new Error('INVALID_MP4');
  }
}
