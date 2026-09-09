function toggleMenu(){document.getElementById("navLinks")?.classList.toggle("open")}
function getLocation(){
  const el=document.getElementById("location");
  if(!navigator.geolocation){alert("Location is not supported. Please enter it manually.");return}
  el.value="Getting your location...";
  navigator.geolocation.getCurrentPosition(
    p=>{el.value=`Latitude: ${p.coords.latitude.toFixed(5)}, Longitude: ${p.coords.longitude.toFixed(5)}`},
    ()=>{el.value="";alert("Unable to get location. Please enter it manually.")}
  );
}
const file=document.getElementById("image");
if(file){
  file.addEventListener("change",function(){
    const f=this.files[0], img=document.getElementById("preview"), text=document.getElementById("uploadText");
    if(f){img.src=URL.createObjectURL(f);img.style.display="block";text.style.display="none";}
  });
}
function filterTable(){
  const q=(document.getElementById("search")?.value||"").toLowerCase();
  document.querySelectorAll("#reportTable tbody tr").forEach(r=>r.style.display=r.innerText.toLowerCase().includes(q)?"":"none");
}
