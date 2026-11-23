// Storage Overview UI component (frontend)
// Renders two horizontal bars: Mac internal storage and external Vault storage.
// Exposes a refresh button that calls the backend API '/api/storage/overview'.

class StorageOverview {
  constructor() {
    this.container = document.getElementById('storage-overview');
    this.refreshBtn = document.getElementById('storage-refresh');
    this.refreshBtn.addEventListener('click', () => this.loadStats());
    this.loadStats();
  }

  async loadStats() {
    try {
      const resp = await fetch('/api/storage/overview');
      const data = await resp.json();
      this.render(data);
    } catch (e) {
      console.error('Failed to load storage overview', e);
    }
  }

  render(stats) {
    // stats: [{label, total_gb, used_gb, free_gb, free_pct}]
    this.container.innerHTML = '';
    stats.forEach(s => {
      const bar = document.createElement('div');
      bar.className = 'storage-bar';
      const pct = Math.round(s.free_pct);
      let color = 'green';
      if (pct < 15) color = 'red';
      else if (pct < 30) color = 'orange';
      bar.style.width = `${100 - pct}%`;
      bar.style.background = color;
      const label = document.createElement('span');
      label.textContent = `${s.label}: ${s.used_gb.toFixed(1)}GB / ${s.total_gb.toFixed(1)}GB (${pct}% free)`;
      this.container.appendChild(label);
      this.container.appendChild(bar);
    });
  }
}

// Initialize when DOM ready
document.addEventListener('DOMContentLoaded', () => new StorageOverview());
