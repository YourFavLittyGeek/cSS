// Settings Sidebar – renders groups A‑E navigation
// This script is imported by the main Settings page.

class SettingsSidebar {
  constructor() {
    this.container = document.getElementById('settings-sidebar');
    this.manifestUrl = '/app/settings/manifest.json';
    this.loadManifest();
  }

  async loadManifest() {
    try {
      const resp = await fetch(this.manifestUrl);
      const manifest = await resp.json();
      this.render(manifest.groups);
    } catch (e) {
      console.error('Failed to load settings manifest', e);
    }
  }

  render(groups) {
    this.container.innerHTML = '';
    Object.entries(groups).forEach(([group, items]) => {
      const groupDiv = document.createElement('div');
      groupDiv.className = 'settings-group';
      const title = document.createElement('h3');
      title.textContent = `Group ${group}`;
      groupDiv.appendChild(title);
      const list = document.createElement('ul');
      items.forEach(item => {
        const li = document.createElement('li');
        const link = document.createElement('a');
        link.href = `#settings/${item.toLowerCase().replace(/ /g, '-')}`;
        link.textContent = item;
        li.appendChild(link);
        list.appendChild(li);
      });
      groupDiv.appendChild(list);
      this.container.appendChild(groupDiv);
    });
  }
}

document.addEventListener('DOMContentLoaded', () => new SettingsSidebar());
