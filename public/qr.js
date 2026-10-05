/**
 * Minimal, zero-dependency QR Code SVG Generator for VYZN Netra.
 * Encodes deep links entirely client-side without external CDNs or network requests.
 * Based on the public domain QR specification (ISO/IEC 18004).
 */

// Error correction and Galois Field tables for compact QR generation
const GF256_EXP = new Uint8Array(512);
const GF256_LOG = new Uint8Array(256);
(function initGF() {
  let val = 1;
  for (let i = 0; i < 255; i++) {
    GF256_EXP[i] = val;
    GF256_EXP[i + 255] = val;
    GF256_LOG[val] = i;
    val = (val << 1) ^ (val & 0x80 ? 0x11d : 0);
  }
})();

function gfMul(x, y) {
  if (x === 0 || y === 0) return 0;
  return GF256_EXP[GF256_LOG[x] + GF256_LOG[y]];
}

function polyMul(p, q) {
  const r = new Uint8Array(p.length + q.length - 1);
  for (let i = 0; i < p.length; i++) {
    for (let j = 0; j < q.length; j++) {
      r[i + j] ^= gfMul(p[i], q[j]);
    }
  }
  return r;
}

function getGenerator(deg) {
  let g = new Uint8Array([1]);
  for (let i = 0; i < deg; i++) {
    g = polyMul(g, new Uint8Array([1, GF256_EXP[i]]));
  }
  return g;
}

function calcEcc(data, eccLen) {
  const gen = getGenerator(eccLen);
  const msg = new Uint8Array(data.length + eccLen);
  msg.set(data);
  for (let i = 0; i < data.length; i++) {
    const lead = msg[i];
    if (lead !== 0) {
      for (let j = 0; j < gen.length; j++) {
        msg[i + j] ^= gfMul(gen[j], lead);
      }
    }
  }
  return msg.slice(data.length);
}

/**
 * Generates an SVG string representation of a QR Code for a given URL string.
 * @param {string} text - The URL or text to encode
 * @param {number} [size=160] - Width and height in px
 * @returns {string} Safe SVG markup
 */
export function generateQrSvg(text, size = 160) {
  // Use Version 4 (33x33 matrix, up to 78 alphanumeric/byte chars in Low ECC)
  // or Version 5 (37x37 matrix) for safe fit of deep link URLs
  const utf8 = new TextEncoder().encode(text);
  const len = utf8.length;
  
  // Select version: V4 (33x33) handles up to 62 bytes, V5 (37x37) up to 84 bytes
  let version = 4;
  let dataCap = 62;
  let eccLen = 18;
  let modCount = 33;
  
  if (len > 60) {
    version = 5;
    dataCap = 84;
    eccLen = 22;
    modCount = 37;
  }

  // 1. Bit stream encoding (Byte mode: 0100 + 8-bit length + data + terminator)
  const bits = [];
  function pushBits(val, count) {
    for (let i = count - 1; i >= 0; i--) {
      bits.push((val >> i) & 1);
    }
  }
  pushBits(0b0100, 4); // Byte mode indicator
  pushBits(len, 8);   // Char count
  for (let b of utf8) {
    pushBits(b, 8);
  }
  // Terminator
  while (bits.length < dataCap * 8 && bits.length % 8 !== 0) {
    bits.push(0);
  }
  // Pad bytes 0xEC, 0x11
  const pad = [0xec, 0x11];
  let padIdx = 0;
  while (bits.length < dataCap * 8) {
    pushBits(pad[padIdx % 2], 8);
    padIdx++;
  }

  // Convert bits to data codewords
  const dataWords = new Uint8Array(dataCap);
  for (let i = 0; i < dataCap; i++) {
    let byteVal = 0;
    for (let b = 0; b < 8; b++) {
      byteVal = (byteVal << 1) | bits[i * 8 + b];
    }
    dataWords[i] = byteVal;
  }

  // Error correction codewords
  const eccWords = calcEcc(dataWords, eccLen);
  const totalWords = new Uint8Array(dataCap + eccLen);
  totalWords.set(dataWords);
  totalWords.set(eccWords, dataCap);

  // 2. Matrix creation & Function patterns
  const matrix = Array.from({ length: modCount }, () => new Array(modCount).fill(null));

  function setFinder(x, y) {
    for (let dy = -1; dy <= 7; dy++) {
      for (let dx = -1; dx <= 7; dx++) {
        const nx = x + dx;
        const ny = y + dy;
        if (nx >= 0 && nx < modCount && ny >= 0 && ny < modCount) {
          const isBorder = (dx >= 0 && dx <= 6 && (dy === 0 || dy === 6)) ||
                           (dy >= 0 && dy <= 6 && (dx === 0 || dx === 6));
          const isCenter = dx >= 2 && dx <= 4 && dy >= 2 && dy <= 4;
          matrix[ny][nx] = (isBorder || isCenter) ? 1 : 0;
        }
      }
    }
  }

  // Place 3 Finder patterns
  setFinder(0, 0);
  setFinder(modCount - 7, 0);
  setFinder(0, modCount - 7);

  // Timing patterns
  for (let i = 8; i < modCount - 8; i++) {
    if (matrix[6][i] === null) matrix[6][i] = (i % 2 === 0) ? 1 : 0;
    if (matrix[i][6] === null) matrix[i][6] = (i % 2 === 0) ? 1 : 0;
  }

  // Dark module
  matrix[modCount - 8][8] = 1;

  // Alignment pattern for V4 (pos 26) or V5 (pos 30)
  const alignPos = version === 4 ? 26 : 30;
  for (let dy = -2; dy <= 2; dy++) {
    for (let dx = -2; dx <= 2; dx++) {
      const isBorder = Math.abs(dx) === 2 || Math.abs(dy) === 2;
      const isCenter = dx === 0 && dy === 0;
      matrix[alignPos + dy][alignPos + dx] = (isBorder || isCenter) ? 1 : 0;
    }
  }

  // Format info area reservation
  for (let i = 0; i < 9; i++) {
    if (matrix[8][i] === null) matrix[8][i] = 0;
    if (matrix[i][8] === null) matrix[i][8] = 0;
  }
  for (let i = modCount - 8; i < modCount; i++) {
    if (matrix[8][i] === null) matrix[8][i] = 0;
    if (matrix[i][8] === null) matrix[i][8] = 0;
  }

  // 3. Fill data bits (zigzag upward & downward)
  let wordIdx = 0;
  let bitIdx = 7;
  let upward = true;

  for (let right = modCount - 1; right > 0; right -= 2) {
    if (right === 6) right--; // Skip vertical timing column
    const rows = upward
      ? Array.from({ length: modCount }, (_, i) => modCount - 1 - i)
      : Array.from({ length: modCount }, (_, i) => i);

    for (let y of rows) {
      for (let x of [right, right - 1]) {
        if (matrix[y][x] === null) {
          let bit = 0;
          if (wordIdx < totalWords.length) {
            bit = (totalWords[wordIdx] >> bitIdx) & 1;
            bitIdx--;
            if (bitIdx < 0) {
              bitIdx = 7;
              wordIdx++;
            }
          }
          // Mask 0: (x + y) % 2 === 0
          if ((x + y) % 2 === 0) {
            bit ^= 1;
          }
          matrix[y][x] = bit;
        }
      }
    }
    upward = !upward;
  }

  // Format string for Error Correction L (01) and Mask 000: format bits 0b111011111000100
  const formatBits = [1,1,1,0,1,1,1,1,1,0,0,0,1,0,0];
  for (let i = 0; i < 6; i++) matrix[8][i] = formatBits[i];
  matrix[8][7] = formatBits[6];
  matrix[8][8] = formatBits[7];
  matrix[7][8] = formatBits[8];
  for (let i = 9; i < 15; i++) matrix[14 - i][8] = formatBits[i];

  for (let i = 0; i < 8; i++) matrix[modCount - 1 - i][8] = formatBits[i];
  for (let i = 8; i < 15; i++) matrix[8][modCount - 15 + i] = formatBits[i];

  // 4. Render clean SVG
  const cell = size / (modCount + 4);
  let rects = '';
  for (let y = 0; y < modCount; y++) {
    for (let x = 0; x < modCount; x++) {
      if (matrix[y][x] === 1) {
        const px = ((x + 2) * cell).toFixed(2);
        const py = ((y + 2) * cell).toFixed(2);
        const c = cell.toFixed(2);
        rects += `<rect x="${px}" y="${py}" width="${c}" height="${c}" fill="currentColor" />`;
      }
    }
  }

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img" aria-label="QR Code for Telegram link" style="background:#ffffff; color:#000000; border-radius:6px; padding:4px;">${rects}</svg>`;
}
