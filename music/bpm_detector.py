import time

import numpy as np


class BeatDetector:
    """Takes a chunk of audio samples, returns True if audio chunk looks like
    bass beat
    """

    def __init__(
        self,
        sample_rate=44100,  #audio samples/sec
        bass_low=20,        #lower bound of bass frequencies
        bass_high=180,      #upper bound of bass frequencies
        sensitivity=1.6,    #how loud bass has to be for beat to be detected
                            #high sensitivity = stricter threshold for beat
        history_size=30,    #window size of normal bass freqs to average over
                            #for normal bass frequency
        cooldown=0.18,      #how much to wait before looking for next beat
        warmup_chunks=5,    #number of chunks to collect before detecting beats
    ):
        self.sample_rate = sample_rate
        self.bass_low = bass_low
        self.bass_high = bass_high
        self.sensitivity = sensitivity
        self.history_size = history_size
        self.cooldown = cooldown
        self.warmup_chunks = warmup_chunks

        self.energy_history = []
        self.last_beat_time = 0.0

    def detect(self, samples):
        """
        Return True when this audio chunk has a bass-energy spike.
        """

        #baseline edge case
        samples = np.asarray(samples, dtype=float)
        if samples.size == 0:
            return False

        #limit how far samples go
        if samples.ndim > 1:
            samples = samples.mean(axis=1)

        #calculate bass energy and average energy, append current sample to history
        bass_energy = self._bass_energy(samples)
        average_energy = self._average_energy()
        self._remember_energy(bass_energy)

        if len(self.energy_history) < self.warmup_chunks:
            return False

        #make sure that waiting period is over
        now = time.time()
        if now - self.last_beat_time < self.cooldown:
            return False

        #prevent false beat triggers
        if average_energy <= 0:
            return False

        #detect if it is a beat
        is_beat = bass_energy > average_energy * self.sensitivity
        if is_beat:
            self.last_beat_time = now  #update last_beat_time

        return is_beat

    def _bass_energy(self, samples):
        """Calculate the energy in the bass frequency range."""
        samples = samples - np.mean(samples) #center around 0
        window = np.hanning(len(samples)) #smooth out with window
        spectrum = np.fft.rfft(samples * window) #convert to freq + add labels
        freqs = np.fft.rfftfreq(len(samples), d=1.0 / self.sample_rate) #convert to freq

        bass_bins = (freqs >= self.bass_low) & (freqs <= self.bass_high) #limit to within bass range
        if not np.any(bass_bins): #make sure there's a bass energy
            return 0.0

        return float(np.mean(np.abs(spectrum[bass_bins]) ** 2))

    def _average_energy(self):
        """Calculate average energy from energy_history for comparison with current audio sample
        to detect possible beats
        """
        if not self.energy_history:
            return 0.0
        return sum(self.energy_history) / len(self.energy_history)  
    
    def _remember_energy(self, energy):
        """Store energy value in energy_history and keep history window size constant
        """
        self.energy_history.append(energy) 
        if len(self.energy_history) > self.history_size: 
            self.energy_history.pop(0)
