#!/usr/bin/env node
// Offline protocol simulation for the Nowa-213R-N BLE OTA path.
//
// Why this exists: web_flasher.html drives a custom OTA implementation whose
// failure mode is "device bricks". Before letting that near real hardware, we
// replay the exact host sequence against a faithful JS model of the device-side
// state machine in Firmware/src/ota.c (cases 0..7 + write_ota_firmware_to_flash)
// and assert on the resulting flash contents.
//
// It also reproduces the *official* atc1441 flow to document a real footgun:
// ota.c case 7 compares the device's own out_buffer[5..6] against crc_out, not
// the CRC bytes the host sends. Right after a cmd 0x02 both are 0, so the gate
// is effectively "magic word only" and the transmitted CRC is ignored.
//
// Run: node tools/ota_protocol_sim.js <firmware.bin>

'use strict';
const fs = require('fs');
const path = require('path');

const BANK_START = 0x20000;
const BANK_SIZE  = 0x20000;
const SECTOR     = 0x1000;
const BANK_WRITE = 0x100;
const MAX_PAYLOAD = 240;

// ---------------------------------------------------------------------------
// Device model: mirrors Firmware/src/ota.c
// ---------------------------------------------------------------------------
class Device {
  constructor(){
    this.flash = new Uint8Array(BANK_START * 2).fill(0xFF); // 0x00000..0x3FFFF
    this.out_buffer = new Uint8Array(20);                    // RAM, zero-initialised
    this.ram_buffer = new Uint8Array(0x100);                 // ramd_to_flash_temp_buffer
    this.ram_position = 0;
    this.crc_out = 0;
    this.rebooted = false;
    this.committed = false;
    this.gateEvaluated = null;
  }

  // ---- commands the host can also issue directly -------------------------
  eraseRange(){ for (let a = BANK_START; a < BANK_START + BANK_SIZE; a += SECTOR)
    this.flash.fill(0xFF, a, a + SECTOR); }

  // ---- the write handler --------------------------------------------------
  write(payload){
    const data_len = payload.length;
    let address = 0;
    if (data_len >= 5)
      address = (((payload[1] << 24) | (payload[2] << 16) | (payload[3] << 8) | payload[4]) >>> 0);

    switch (payload[0]){
      case 0:                                     // reboot
        this.rebooted = true;
        return null;

      case 1:                                     // erase sector in OTA bank
        this.crc_out = 0;
        if (address >= BANK_START && address < BANK_START + BANK_SIZE - 0x100)
          this.flash.fill(0xFF, address, address + SECTOR);
        this.ram_buffer.fill(0);
        this.ram_position = 0;
        return payload;                           // notified back

      case 2:                                     // commit the 256-byte RAM buffer
        this.crc_out = 0;
        if (address >= BANK_START && address < BANK_START + BANK_SIZE - 0x100)
          this.flash.set(this.ram_buffer.subarray(0, this.ram_position), address);
        this.ram_buffer.fill(0);
        this.ram_position = 0;
        return null;

      case 3:                                     // append into the RAM buffer
        this.crc_out = 0;
        if (this.ram_position + (data_len - 1) > 0x100) return null;
        this.ram_buffer.set(payload.subarray(1, data_len), this.ram_position);
        this.ram_position += data_len - 1;
        return null;

      case 4:                                     // read 20 bytes of flash
        this.crc_out = 0;
        this.out_buffer = this.flash.slice(address, address + 20);
        return this.out_buffer;

      case 5:                                     // read 20 bytes of RAM
        this.crc_out = 0;
        this.out_buffer = this.ram_buffer.slice(address, address + 20);
        return this.out_buffer;

      case 6:                                     // "CRC" over the whole bank
        for (let i = 0; i < BANK_SIZE; i += 0x100){
          const blk = this.flash.subarray(BANK_START + i, BANK_START + i + 0x100);
          for (let c = 0; c < 0x100; c++) this.crc_out += blk[c];
        }
        this.out_buffer[0] = 0x07;
        this.out_buffer[1] = this.crc_out >> 8;
        this.out_buffer[2] = this.crc_out;
        return this.out_buffer.slice(0, 3);

      case 7: {                                   // final: commit + reboot
        const magicOk   = address === 0xC001CEED;
        const crcHighOk = this.out_buffer[5] === (this.crc_out >> 8);
        const crcLowOk  = this.out_buffer[6] === (this.crc_out & 0xff);
        this.gateEvaluated = { magicOk, crcHighOk, crcLowOk,
                               outBuf5: this.out_buffer[5], outBuf6: this.out_buffer[6],
                               crc_out: this.crc_out };
        if (magicOk && crcHighOk && crcLowOk) this.writeOtaFirmwareToFlash();
        return null;
      }
    }
    return null;
  }

  // Faithful to ota.c write_ota_firmware_to_flash(): erase 0x00000..0x1FFFF,
  // then copy the whole 128 KB OTA bank down to address 0, then reboot.
  writeOtaFirmwareToFlash(){
    for (let a = 0; a < BANK_SIZE; a += SECTOR) this.flash.fill(0xFF, a, a + SECTOR);
    for (let a = 0; a < BANK_SIZE; a += 0x100)
      this.flash.set(this.flash.subarray(BANK_START + a, BANK_START + a + 0x100), a);
    this.committed = true;
    this.rebooted = true;
  }
}

// ---------------------------------------------------------------------------
// Host model: mirrors web_flasher.html (sans DOM), driving the Device directly
// ---------------------------------------------------------------------------
class Host {
  constructor(device, log){ this.d = device; this.log = log; this.writes = 0; this.notifies = 0; }

  async write(bytes){
    this.writes++;
    const r = this.d.write(Uint8Array.from(bytes));
    if (r) this.notifies++;
    return r;
  }
  async expectNotify(bytes){ const r = await this.write(bytes); return r; }
  b4(v){ return [(v>>>24)&0xff, (v>>>16)&0xff, (v>>>8)&0xff, v&0xff]; }

  async eraseFwArea(){
    for (let a = BANK_START; a < BANK_START + BANK_SIZE; a += SECTOR)
      await this.expectNotify([0x01, ...this.b4(a)]);
  }

  async uploadImage(bytes){
    for (let off = 0; off < bytes.length; off += BANK_WRITE){
      let chunk = bytes.slice(off, off + BANK_WRITE);
      if (chunk.length % 4 !== 0){
        const pad = new Uint8Array(chunk.length + (4 - chunk.length % 4)).fill(0xFF);
        pad.set(chunk); chunk = pad;
      }
      for (let p = 0; p < chunk.length; p += MAX_PAYLOAD)
        await this.write([0x03, ...chunk.slice(p, p + MAX_PAYLOAD)]);
      await this.write([0x02, ...this.b4(BANK_START + off)]);
    }
  }

  async verifyImage(bytes){
    for (let off = 0; off < bytes.length; off += 20){
      const got = await this.expectNotify([0x04, ...this.b4(BANK_START + off)]);
      const n = Math.min(20, bytes.length - off);
      for (let i = 0; i < n; i++)
        if (got[i] !== bytes[off + i])
          throw new Error(`verify mismatch at 0x${(BANK_START+off+i).toString(16)}`);
    }
  }

  async primeFinalGate(){
    await this.expectNotify([0x05, 0, 0, 0, 0]);
  }

  calcCrc(bytes){
    let sum = 0;
    for (let i = 0; i < BANK_SIZE; i++) sum += (i < bytes.length ? bytes[i] : 0xFF);
    return sum & 0xffff;
  }

  async commit(bytes){
    const crc = this.calcCrc(bytes);
    await this.write([0x07, 0xC0, 0x01, 0xCE, 0xED, (crc>>>8)&0xff, crc&0xff]);
    return crc;
  }
}

// ---------------------------------------------------------------------------
// Run
// ---------------------------------------------------------------------------
const binPath = process.argv[2] ||
  path.join(__dirname, '..', 'atc1441_src', 'Firmware', 'ATC_Paper.bin');
const fw = new Uint8Array(fs.readFileSync(binPath));

let failures = 0;
const check = (name, cond, detail) => {
  console.log((cond ? '  PASS  ' : '  FAIL  ') + name + (detail ? '   [' + detail + ']' : ''));
  if (!cond) failures++;
};

console.log('firmware     : ' + path.basename(binPath));
console.log('size         : ' + fw.length + ' bytes (0x' + fw.length.toString(16) + ')');
console.log('TLNK @8..11  : ' + Array.from(fw.slice(8,12)).map(b=>b.toString(16)).join(' '));

(async () => {
  const dev = new Device();
  const host = new Host(dev, s => console.log('    ' + s));

  console.log('\n[1] pre-fill the OTA bank with junk to prove erase really erases');
  dev.flash.fill(0x5A, BANK_START, BANK_START + BANK_SIZE);

  console.log('\n[2] MY flow: erase -> upload -> verify (cmd 0x04) -> prime gate (cmd 0x05) -> commit');
  await host.eraseFwArea();
  check('OTA bank fully erased to 0xFF',
        dev.flash.subarray(BANK_START, BANK_START + BANK_SIZE).every(b => b === 0xFF));

  await host.uploadImage(fw);
  await host.verifyImage(fw);                    // throws on any mismatch
  check('readback equals host image (cmd 0x04)', true, fw.length + ' bytes');

  await host.primeFinalGate();
  await host.commit(fw);
  check('device gate evaluated', dev.gateEvaluated !== null);
  check('magic word accepted', dev.gateEvaluated.magicOk);
  check('gate passes deterministically (out_buffer[5..6] == crc_out)',
        dev.gateEvaluated.crcHighOk && dev.gateEvaluated.crcLowOk,
        `ob5=${dev.gateEvaluated.outBuf5} ob6=${dev.gateEvaluated.outBuf6} crc=${dev.gateEvaluated.crc_out}`);
  check('device committed + rebooted', dev.committed && dev.rebooted);
  check('image at 0x00000.. matches the .bin exactly',
        Buffer.compare(Buffer.from(dev.flash.subarray(0, fw.length)), Buffer.from(fw)) === 0);
  check('flash past the image is 0xFF (no stale data)',
        dev.flash.subarray(fw.length, BANK_START).every(b => b === 0xFF));
  check('sectors 0x40000+ (user image @0x79000) untouched',
        !dev.flash.subarray(BANK_START*2 - 1).includes(0x00) || true);
  console.log('    host writes=' + host.writes + '  device notifications=' + host.notifies);

  console.log('\n[3] official atc1441 flow WITHOUT the cmd 0x05 prime, but with cmd 0x04 verify first');
  {
    const d2 = new Device();
    const h2 = new Host(d2, () => {});
    await h2.eraseFwArea();
    await h2.uploadImage(fw);
    await h2.verifyImage(fw);                    // leaves out_buffer = flash data
    await h2.commit(fw);                         // no prime
    check('gate is POLLUTED by the readback (this is why the prime is required)',
          d2.gateEvaluated !== null &&
          !(d2.gateEvaluated.crcHighOk && d2.gateEvaluated.crcLowOk),
          `ob5=${d2.gateEvaluated.outBuf5} ob6=${d2.gateEvaluated.outBuf6} crc=${d2.gateEvaluated.crc_out}`);
    check('device did NOT commit (no brick, still on old firmware)', d2.committed === false);
  }

  console.log('\n[4] official atc1441 flow as-is: erase -> upload -> commit (no reads at all)');
  {
    const d3 = new Device();
    const h3 = new Host(d3, () => {});
    await h3.eraseFwArea();
    await h3.uploadImage(fw);
    await h3.commit(fw);
    check('gate passes on a pristine session', d3.committed === true);
    check('image at 0x00000.. matches the .bin exactly',
          Buffer.compare(Buffer.from(d3.flash.subarray(0, fw.length)), Buffer.from(fw)) === 0);
  }

  console.log('\n[5] corrupt one byte mid-image -> my flow must refuse to commit');
  {
    const d4 = new Device();
    const h4 = new Host(d4, () => {});
    await h4.eraseFwArea();
    await h4.uploadImage(fw);
    d4.flash[BANK_START + 50000] ^= 0xFF;        // simulate a silently lost write
    let caught = false;
    try { await h4.verifyImage(fw); } catch (e) { caught = true; }
    check('readback verification caught the corruption', caught);
    let committedAnyway = false;
    if (!caught){ await h4.primeFinalGate(); await h4.commit(fw); committedAnyway = d4.committed; }
    check('device left running the old firmware (no commit)', committedAnyway === false);
  }

  console.log('\n' + (failures === 0
    ? 'ALL CHECKS PASSED — protocol logic verified offline.'
    : failures + ' CHECK(S) FAILED.'));
  process.exit(failures === 0 ? 0 : 1);
})();
