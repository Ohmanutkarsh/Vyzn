'use client';

import React from 'react';
import { Camera, Wifi, Smartphone, ArrowRight } from 'lucide-react';

interface ConnectionOption {
  id: 'ip' | 'network' | 'phone';
  title: string;
  badge: {
    label: string;
    className: string;
  };
  description: string;
  tags: string;
  icon: React.ComponentType<{ className?: string }>;
}

const CONNECTION_OPTIONS: ConnectionOption[] = [
  {
    id: 'ip',
    title: 'IP camera or recorder',
    badge: {
      label: 'Direct RTSP',
      className: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
    },
    description: 'CCTV camera, DVR, or NVR. Connect directly using its local IP address and credentials.',
    tags: 'Hikvision • CP Plus • Dahua • ONVIF / NVR',
    icon: Camera,
  },
  {
    id: 'network',
    title: 'Find on my network',
    badge: {
      label: 'Auto-Discovery',
      className: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    },
    description: "VYZN scans your shop's Wi-Fi and local network for active CCTV feeds automatically.",
    tags: 'Zero Setup • Auto-Detect Local Subnet',
    icon: Wifi,
  },
  {
    id: 'phone',
    title: 'Phone or webcam',
    badge: {
      label: 'Instant Test',
      className: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
    },
    description: "Use a spare phone running IP Webcam, or this computer's webcam for instant testing.",
    tags: 'Computer Webcam • Android / iOS App',
    icon: Smartphone,
  },
];

interface AddCameraStep1Props {
  onSelectOption?: (optionId: 'ip' | 'network' | 'phone') => void;
  onStepChange?: (step: number) => void;
  currentStep?: number;
  totalSteps?: number;
}

export default function AddCameraStep1({
  onSelectOption,
  onStepChange,
  currentStep = 1,
  totalSteps = 3,
}: AddCameraStep1Props) {
  return (
    <div className="w-full min-h-screen bg-zinc-950 text-zinc-100 antialiased overflow-x-hidden">
      <main className="max-w-2xl mx-auto py-12 px-6">
        {/* Step Indicator */}
        <div
          className="text-xs font-semibold tracking-widest uppercase text-zinc-500 hover:text-zinc-300 mb-2 select-none cursor-pointer inline-block transition-colors"
          onClick={() => onStepChange?.(1)}
          title="Return to Step 1"
        >
          STEP {currentStep} OF {totalSteps}
        </div>

        {/* Main Heading */}
        <h1 className="text-3xl font-bold tracking-tight text-white mb-2">
          How is the camera connected?
        </h1>

        {/* Sub-caption */}
        <p className="text-sm text-zinc-400 mb-8">
          Select a connection method to stream footage into VYZN.
        </p>

        {/* Connection Method Selection Cards */}
        <div className="flex flex-col gap-3.5">
          {CONNECTION_OPTIONS.map((option) => {
            const Icon = option.icon;
            return (
              <button
                key={option.id}
                type="button"
                onClick={() => onSelectOption?.(option.id)}
                className="w-full text-left bg-zinc-900/60 border border-zinc-800 hover:border-zinc-700 hover:bg-zinc-900/90 rounded-xl p-5 transition-all duration-150 cursor-pointer group flex items-start justify-between focus:outline-none focus:ring-2 focus:ring-zinc-600/50"
              >
                {/* Left Slot: Icon */}
                <div className="p-2.5 rounded-lg bg-zinc-800/60 border border-zinc-700/50 text-zinc-300 group-hover:text-white mr-4 shrink-0 transition-colors">
                  <Icon className="w-5 h-5" />
                </div>

                {/* Middle Slot: Content */}
                <div className="flex-1 min-w-0 flex flex-col">
                  {/* Title & Badge Row */}
                  <div className="flex items-center flex-wrap gap-2">
                    <span className="text-base font-semibold text-white">
                      {option.title}
                    </span>
                    <span
                      className={`text-[11px] font-medium px-2 py-0.5 rounded-full border ${option.badge.className}`}
                    >
                      {option.badge.label}
                    </span>
                  </div>

                  {/* Description */}
                  <p className="text-sm text-zinc-400 mt-1 mb-2 leading-relaxed">
                    {option.description}
                  </p>

                  {/* Supported Tags */}
                  <span className="text-xs text-zinc-500 font-mono tracking-tight">
                    {option.tags}
                  </span>
                </div>

                {/* Right Slot: Arrow */}
                <div className="text-zinc-600 group-hover:text-white group-hover:translate-x-0.5 transition-all mt-1 ml-3 shrink-0">
                  <ArrowRight className="w-4 h-4" />
                </div>
              </button>
            );
          })}
        </div>

        {/* Stepper Progress Indicator */}
        <div className="mt-10 flex items-center justify-between gap-4 select-none">
          <div
            className="h-1.5 bg-zinc-800 hover:bg-zinc-700/80 rounded-full flex-1 overflow-hidden cursor-pointer transition-colors"
            title="Click to jump to a step"
            onClick={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              const ratio = (e.clientX - rect.left) / rect.width;
              const nextStep = ratio <= 0.35 ? 1 : ratio <= 0.7 ? 2 : 3;
              onStepChange?.(nextStep);
            }}
          >
            <div
              className="h-full bg-blue-500 rounded-full transition-all duration-300 pointer-events-none"
              style={{ width: `${(currentStep / totalSteps) * 100}%` }}
            />
          </div>
          <span
            className="text-xs font-mono text-zinc-500 hover:text-white cursor-pointer transition-colors"
            title="Click to cycle steps"
            onClick={() => {
              const nextStep = currentStep >= totalSteps ? 1 : currentStep + 1;
              onStepChange?.(nextStep);
            }}
          >
            {currentStep}/{totalSteps}
          </span>
        </div>
      </main>
    </div>
  );
}
