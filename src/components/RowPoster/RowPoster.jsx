// Adapted from Th3Wall/Fakeflix: MIT. Touch opens details without hover controls.
export default function RowPoster({item,onOpen}){
 const image=typeof item.cover==='object'?item.cover?.url:item.cover||item.poster;
 return <button className="movie-card" onClick={()=>onOpen(item)} aria-label={`View ${item.title}`}>
  <div className="poster">{image?<img src={image} alt="" loading="lazy" onError={e=>e.currentTarget.style.display='none'}/>:<span>{item.title}</span>}{item.score&&<span className="rating">★ {item.score}</span>}</div>
  <strong>{item.title}</strong><small>{item.releaseTime?.slice(0,4)||'MovieBox'} · {Number(item.subjectType)===2?'Series':'Movie'}</small>
 </button>
}
