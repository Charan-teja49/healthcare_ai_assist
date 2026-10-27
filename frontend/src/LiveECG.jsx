import { t } from "./i18n.js";
import React, { useEffect, useRef } from 'react';
export default function LiveECG({
  samples = [],
  sampleRate = 250,
  signal = true,
  staticWindow = false,
  highlight = null
}) {
  const canvas = useRef(null),
    buffer = useRef([]);
  useEffect(() => {
    if (!signal || !samples.length) buffer.current=[];
    else buffer.current=staticWindow?samples:[...buffer.current,...samples].slice(-2500);
  }, [samples,signal,staticWindow]);
  useEffect(() => {
    let frame;
    function draw() {
      const node = canvas.current;
      if (!node) return;
      const ratio = window.devicePixelRatio || 1;
      const width = node.clientWidth || 800,
        height = 120;
      if (node.width !== width * ratio) {
        node.width = width * ratio;
        node.height = height * ratio;
      }
      const c = node.getContext('2d');
      c.setTransform(ratio, 0, 0, ratio, 0, 0);
      c.fillStyle = '#f8fbf8';
      c.fillRect(0, 0, width, height);
      c.strokeStyle = '#d4e8e2';
      c.lineWidth = .5;
      for (let x = 0; x < width; x += 20) {
        c.beginPath();
        c.moveTo(x, 0);
        c.lineTo(x, height);
        c.stroke();
      }
      for (let y = 0; y < height; y += 20) {
        c.beginPath();
        c.moveTo(0, y);
        c.lineTo(width, y);
        c.stroke();
      }
      const data = signal ? (staticWindow?buffer.current:buffer.current.slice(-sampleRate * 4)) : [];
      if (highlight && buffer.current.length) {
        c.fillStyle = '#fbe9dd';
        c.fillRect(Math.max(0,highlight.start) / data.length * width, 0, Math.max(0,Math.min(highlight.end,data.length)-Math.max(0,highlight.start)) / data.length * width, height);
      }
      c.strokeStyle = '#268c76';
      c.lineWidth = 1.6;
      c.beginPath();
      if (data.length) {
        data.forEach((v, i) => {
          const x = i / Math.max(data.length - 1, 1) * width,
            y = 60 - v * 35;
          i ? c.lineTo(x, y) : c.moveTo(x, y);
        });
      } else {
        c.moveTo(0, 60);
        c.lineTo(width, 60);
      }
      c.stroke();
      frame = requestAnimationFrame(draw);
    }
    draw();
    return () => cancelAnimationFrame(frame);
  }, [sampleRate, signal, highlight,staticWindow]);
  return <div><canvas ref={canvas} style={{
      width: '100%',
      height: 120
    }} aria-label={t("Streaming ECG waveform")} /><small>{samples.length ? sampleRate + ' Hz resampled waveform · verify signal source' : t("Waiting for an ECG packet; no signal is fabricated")}</small></div>;
}
