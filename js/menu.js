
// Menu model
const menus = [
  // Book
  {
    type: 'mega',
    label: 'Book',
    sections: [
      { header: 'Appointments', links: [
        { label: 'Book an Appointment', href: '#book' },
        { label: 'Refer a patient', href: '#book' },
        { label: 'Fees', href: 'General_Fees.html' }
      ]},
      { header: 'Hospitals & Locations', links: [
        { label: 'The Wellington Hospital', href: 'Locations_The_Wellington_Hospital.html' },
        { label: 'King’s College Hospital', href: 'Locations_Kings_College_Hospital.html' },
        { label: 'Queen’s Hospital Romford', href: 'Locations_Queens_Hospital_in_Romford.html' }
      ]},
      { header: 'Information', links: [
        { label: 'Cancellations', href: 'General_Cancellations.html' },
        { label: 'Terms & Conditions', href: 'General_Terms_and_Conditions.html' }
      ]}
    ]
  },

  // About
  {
    type: 'mega',
    label: 'About',
    sections: [
      { header: 'About Dr Lynch', links: [
        { label: 'Profile', href: 'General_About_Dr_Lynch.html' }
      ]},
      { header: 'Research', links: [
        { label: 'Research & Publications', href: 'General_Research.html' }
      ]},
      { header: 'Fellowship', links: [
        { label: 'Fellowship Information', href: 'General_Fellowship.html' }
      ]}
    ]
  },

  // Treatments & Diagnostics
  {
    type: 'mega',
    label: 'Treatments & Diagnostics',
    sections: [
      { header: 'Brain', links: [
        { label: 'Brain Aneurysms', href: 'Aneurysms_Introduction_to_brain_aneurysms.html' },
        { label: 'AVMs', href: 'AVM_Introduction_to_AVMs.html' },
        { label: 'Dural Fistulas (DAVFs)', href: 'DAVF_Introduction_to_DAVF.html' },
        { label: 'Stroke', href: 'Stroke_Introduction_to_stroke.html' },
        { label: 'Pulsatile Tinnitus', href: 'Pulsatile_Tinnitus_Introduction_to_Pulsatile_Tinnitus.html' },
        { label: 'Idiopathic Intracranial Hypertension', href: 'Idiopathic_Intracranial_Hypertension_Introduction_to_idiopathic_Intracranial_Hypertension.html' },
        { label: 'Spontaneous Intracranial Hypotension', href: 'Spontaneous_Intracranial_Hypotension_Introduction_to_Spontaneous_Intracranial_Hypotension.html' }
      ]},
      { header: 'Spine', links: [
        { label: 'Spinal Vascular Disease', href: 'Spinal_Introduction_to_spinal_vascular_disease.html' }
      ]},
      { header: 'Diagnostics', links: [
        { label: 'MRI', href: 'MRI.html' },
        { label: 'CT', href: 'CT.html' },
        { label: 'Cerebral Angiography', href: 'Angiography_Cerebral_angiography.html' },
        { label: 'Spinal Angiography', href: 'Angiography_Spinal_angiography.html' }
      ]}
    ]
  },

  // Articles
  {
    type: 'mega',
    label: 'Articles',
    sections: [
      { header: 'Patient Resources', links: [
        { label: 'All Topics', href: 'All_topics.html' },
        { label: 'Featured Articles', href: 'Features.html' }
      ]},
      { header: 'Essential Knowledge', links: [
        { label: 'About the Brain', href: 'Essential_knowledge_About_the_brain.html' },
        { label: 'About the Spine', href: 'Essential_knowledge_About_the_spine.html' },
        { label: 'Glossary', href: 'Essential_knowledge_Glossary.html' }
      ]}
    ]
  }
]



      // Build desktop bar
      const desktop = document.getElementById('desktopTopLevel')
      desktop.innerHTML = menus.map((menu, idx) => {
        if (menu.type === 'link') {
          return `
            <li class="nav-item">
              <a class="nav-link px-3" href="${menu.href}">${menu.label}</a>
            </li>
          `
        }
        return `
          <li class="nav-item dropdown">
            <a class="nav-link px-3" href="#" id="top${idx}" role="button" data-bs-toggle="dropdown" aria-expanded="false">
              ${menu.label}
            </a>
            <div class="dropdown-menu p-4" aria-labelledby="top${idx}">
              <div>
                <div class="row" style="padding-left: 30%; padding-right: 20%">
                  ${menu.sections.map(s => `
                    <div class="col mega-col mb-3">
                      <h6>${s.header}</h6>
                      ${s.links.map(l => {
                        const external = l.href.startsWith('http')
                        return `<a class="link-body-emphasis text-decoration-none d-block py-1" href="${l.href}" ${external ? 'target="_blank" rel="noopener"' : ''}>${l.label}</a>`
                      }).join('')}
                    </div>
                  `).join('')}
                </div>
              </div>
            </div>
          </li>
        `
      }).join('')

      // Build mobile accordion: top level only, tap to reveal, one open at a time
      const mobile = document.getElementById('mobileMenu')
      const accordionId = 'mobileAccordion'
      mobile.innerHTML = `<div class="accordion" id="${accordionId}" role="tablist"></div>`
      const acc = mobile.querySelector('.accordion')

      menus.forEach((menu, idx) => {
        // Simple one-click link at top level
        if (menu.type === 'link') {
          acc.insertAdjacentHTML('beforeend', `
            <div class="py-2">
              <a class="fw-semibold d-block" href="${menu.href}">${menu.label}</a>
            </div>
          `)
          return
        }

        // Accordion item for a mega menu
        const headingId = `acc-heading-${idx}`
        const panelId = `acc-panel-${idx}`

        const sectionsHtml = menu.sections.map(s => `
          <div class="mt-2">
            <h6 class="text-uppercase text-muted mb-1">${s.header}</h6>
            ${s.links.map(l => {
              const external = l.href.startsWith('http')
              const attrs = external ? 'target="_blank" rel="noopener"' : ''
              return `<a class="py-1 d-block" href="${l.href}" ${attrs}>${l.label}</a>`
            }).join('')}
          </div>
        `).join('')

        acc.insertAdjacentHTML('beforeend', `
          <div class="accordion-item">
            <h2 class="accordion-header" id="${headingId}">
              <button class="accordion-button collapsed" type="button"
                      data-bs-toggle="collapse" data-bs-target="#${panelId}"
                      aria-expanded="false" aria-controls="${panelId}">
                ${menu.label}
              </button>
            </h2>
            <div id="${panelId}" class="accordion-collapse collapse"
                 role="region" aria-labelledby="${headingId}"
                 data-bs-parent="#${accordionId}">
              <div class="accordion-body">
                ${sectionsHtml}
              </div>
            </div>
          </div>
        `)
      })

      // Behaviour elements
      const mobileNavEl = document.getElementById('mobileNav')

      // Close drawer after choosing a leaf link
      mobile.addEventListener('click', e => {
        const a = e.target.closest('a[href]')
        if (!a) return
        const inst = bootstrap.Collapse.getOrCreateInstance(mobileNavEl, { toggle: false })
        inst.hide()
      })

      // Reset open panels when the drawer closes
      mobileNavEl.addEventListener('hide.bs.collapse', e => {
        if (e.target !== mobileNavEl) return
        document.querySelectorAll(`#${accordionId} .accordion-collapse.show`).forEach(p => {
          const inst = bootstrap.Collapse.getOrCreateInstance(p, { toggle: false })
          inst.hide()
        })
      })

      // Focus the first top level when the drawer opens
      mobileNavEl.addEventListener('shown.bs.collapse', e => {
        if (e.target !== mobileNavEl) return
        const firstBtn = mobile.querySelector('.accordion-button, a.fw-semibold')
        if (firstBtn) firstBtn.focus()
      })

      // Deep-link awareness: open the panel that contains the current page
      const here = location.pathname.split('/').pop()
      if (here) {
        const match = mobile.querySelector(`.accordion-body a[href$="${here}"]`)
        if (match) {
          const panel = match.closest('.accordion-collapse')
          const inst = bootstrap.Collapse.getOrCreateInstance(panel, { toggle: false })
          inst.show()
        }
      }

      // ==== Body lock + backdrop logic ====
      const backdrop = document.getElementById('menuBackdrop')
      let blockTouch = null

      function lockBody(){
  document.body.classList.add('body-lock')
  backdrop.hidden = false
  // prevent interaction with background
  const main = document.querySelector('main')
  const footer = document.querySelector('footer, #footer') || document.getElementById('footer')
  main && main.setAttribute('inert', '')
  footer && footer.setAttribute('inert', '')
  requestAnimationFrame(() => backdrop.classList.add('show'))
}


function unlockBody(){
  document.body.classList.remove('body-lock')
  backdrop.classList.remove('show')
  backdrop.hidden = true
  const main = document.querySelector('main')
  const footer = document.querySelector('footer, #footer') || document.getElementById('footer')
  main && main.removeAttribute('inert')
  footer && footer.removeAttribute('inert')
}


      // Only react when the top-level drawer opens or closes
      mobileNavEl.addEventListener('show.bs.collapse', e => {
        if (e.target !== mobileNavEl) return
        lockBody()
      })
      mobileNavEl.addEventListener('hidden.bs.collapse', e => {
        if (e.target !== mobileNavEl) return
        unlockBody()
      })

      // Stop inner accordion collapse events bubbling up and affecting backdrop
      document.querySelectorAll('#mobileMenu .accordion-collapse').forEach(p => {
        p.addEventListener('show.bs.collapse', e => e.stopPropagation())
        p.addEventListener('hide.bs.collapse', e => e.stopPropagation())
      })

      // Tap on the grey background closes the whole menu
      backdrop.addEventListener('click', () => {
        const inst = bootstrap.Collapse.getOrCreateInstance(mobileNavEl, { toggle: false })
        inst.hide()
      })

      // Close with Esc
      document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && mobileNavEl.classList.contains('show')) {
          const inst = bootstrap.Collapse.getOrCreateInstance(mobileNavEl, { toggle: false })
          inst.hide()
        }
      })
      
      
      
