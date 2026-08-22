import { ROUTES } from '../router'
import { Link } from '../ui/Link'

export default function NotFound() {
  return (
    <main className="tl-shell tl-lead" style={{ paddingBottom: '22vh' }}>
      <h1 className="tl-h1">이 주소에는 아무것도 없습니다</h1>
      <p className="tl-lede" style={{ marginTop: 14 }}>주소를 잘못 입력했거나, 없어진 페이지입니다.</p>
      <div className="tl-actions" style={{ marginTop: 24 }}>
        <Link to={ROUTES.landing} className="tl-btn">
          처음으로
        </Link>
        <Link to={ROUTES.app} className="tl-btn tl-btn--quiet">
          실행 화면으로
        </Link>
      </div>
    </main>
  )
}
